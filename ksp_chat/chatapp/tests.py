import json
from datetime import datetime, timedelta, timezone

from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from jose import jwt

from .authentication import AUTH_COOKIE_NAME
from .channels_auth import JWTAuthMiddlewareStack
from .models import AppUser
from .routing import websocket_urlpatterns


class RequestLoggingTests(TestCase):
    """Verifies the two guarantees the logging redesign exists for: a
    request can be traced end-to-end via a shared request_id, and secret
    material never ends up in a log record."""

    def test_request_started_and_completed_share_one_request_id(self):
        # unittest's assertLogs isn't usable here: it works by swapping the
        # named logger's handlers and forcing propagate=False for the
        # duration, which — by design (see settings.LOGGING's own comment)
        # — is exactly where RequestContextFilter lives, so a record
        # captured that way would never actually pass through it. Reading
        # app.log instead exercises the real pipeline: middleware -> filter
        # -> JSONFormatter -> file, the same path a developer grepping this
        # file for a request_id relies on.
        log_path = settings.BASE_DIR / "logs" / "app.log"
        offset_before = log_path.stat().st_size if log_path.exists() else 0

        self.client.get("/login/")

        with open(log_path, "r", encoding="utf-8") as f:
            f.seek(offset_before)
            new_records = [json.loads(line) for line in f if line.strip()]

        request_events = {
            rec["event"]: rec for rec in new_records
            if rec.get("event") in ("request_started", "request_completed") and rec.get("endpoint") == "/login/"
        }
        self.assertIn("request_started", request_events)
        self.assertIn("request_completed", request_events)
        self.assertEqual(
            request_events["request_started"]["request_id"],
            request_events["request_completed"]["request_id"],
        )

    def test_login_attempt_never_logs_the_password(self):
        secret = "sekrit-test-password-should-never-appear-in-logs"
        with self.assertLogs("chatapp", level="DEBUG") as captured:
            self.client.post("/login/", {"username": "someone", "password": secret})

        for record in captured.records:
            self.assertNotIn(secret, record.getMessage())


@override_settings(AUTH_JWT_SECRET_KEY="test-secret-key", AUTH_JWT_ALGORITHM="HS256")
class WebSocketBanCheckTests(TestCase):
    """channels_auth.JWTAuthMiddleware used to skip the local ban check that
    the HTTP-side JWTAuthenticationMiddleware applies — a banned user's
    still-cryptographically-valid token could still open /ws/logs/. This
    confirms the two transports now agree on what "banned" means.

    Built directly from JWTAuthMiddlewareStack(URLRouter(...)) — the actual
    unit under test — rather than the full ksp_chat.asgi.application: that
    full stack also passes through AllowedHostsOriginValidator, an
    unrelated pre-existing layer with its own Origin-header requirements
    that would otherwise make every connection attempt here fail
    regardless of ban status, for a reason this test isn't about."""

    application = JWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns))

    @staticmethod
    def _token_for(username):
        return jwt.encode(
            {"sub": username, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            "test-secret-key",
            algorithm="HS256",
        )

    async def test_banned_user_cannot_open_log_socket(self):
        await sync_to_async(AppUser.objects.create)(username="banneduser", is_active=False)
        token = self._token_for("banneduser")

        communicator = WebsocketCommunicator(
            self.application, "/ws/logs/",
            headers=[(b"cookie", f"{AUTH_COOKIE_NAME}={token}".encode())],
        )
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_active_user_can_open_log_socket(self):
        await sync_to_async(AppUser.objects.create)(username="activeuser", is_active=True)
        token = self._token_for("activeuser")

        communicator = WebsocketCommunicator(
            self.application, "/ws/logs/",
            headers=[(b"cookie", f"{AUTH_COOKIE_NAME}={token}".encode())],
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()


class DjangoAdminGateTests(TestCase):
    def test_admin_site_is_unreachable_by_default(self):
        # DJANGO_ADMIN_ENABLED defaults to False (see settings.py) — this
        # confirms /admin/ isn't wired into urlpatterns at all in that case,
        # rather than merely being auth-gated.
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 404)


@override_settings(AUTH_JWT_SECRET_KEY="test-secret-key", AUTH_JWT_ALGORITHM="HS256")
class UploadRegressionTests(TestCase):
    """A prior version used "filename" as a custom extra= logging field —
    which collides with LogRecord's own built-in `filename` attribute (the
    source file the log call was made from), so logging.Logger raises
    KeyError the instant that line runs. That crashed every /upload/
    request with an unhandled 500, before RAGService/Gemini were ever
    involved. This confirms the view's own logging no longer crashes it —
    it doesn't need a real Gemini key to prove that, since the bug fired at
    the very first log line, before any external call."""

    def test_upload_does_not_500_on_the_upload_started_log_line(self):
        token = jwt.encode(
            {"sub": "uploaduser", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            "test-secret-key", algorithm="HS256",
        )
        self.client.cookies[AUTH_COOKIE_NAME] = token

        upload = SimpleUploadedFile("note.txt", b"hello world", content_type="text/plain")
        response = self.client.post("/upload/", {"file": upload})

        self.assertNotEqual(response.status_code, 500)


@override_settings(AUTH_JWT_SECRET_KEY="test-secret-key", AUTH_JWT_ALGORITHM="HS256")
class AdminRoleGateTests(TestCase):
    """Admin is now a real JWT role claim, not a separate hardcoded
    identity — confirms admin_auth.admin_page_required reads it correctly:
    anonymous -> /login/, authenticated-but-not-admin -> chat index,
    role=admin -> the dashboard itself."""

    @staticmethod
    def _token_for(username, role):
        return jwt.encode(
            {"sub": username, "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            "test-secret-key",
            algorithm="HS256",
        )

    def test_anonymous_request_redirects_to_login(self):
        response = self.client.get("/users/")
        self.assertRedirects(response, "/login/")

    def test_non_admin_request_redirects_to_chat_index(self):
        self.client.cookies[AUTH_COOKIE_NAME] = self._token_for("regularuser", "user")
        response = self.client.get("/users/")
        self.assertRedirects(response, "/")

    def test_admin_request_reaches_the_dashboard(self):
        self.client.cookies[AUTH_COOKIE_NAME] = self._token_for("adminuser", "admin")
        response = self.client.get("/users/")
        self.assertEqual(response.status_code, 200)

    def test_admin_is_redirected_away_from_chat_index(self):
        # An admin might still own chat history from before being promoted
        # (or just type the URL) — confirms login_required now refuses that
        # rather than serving the regular chat UI to an admin-role account.
        self.client.cookies[AUTH_COOKIE_NAME] = self._token_for("adminuser", "admin")
        response = self.client.get("/")
        self.assertRedirects(response, "/users/")

    def test_admin_is_refused_on_chat_ajax_endpoints(self):
        # Same restriction on jwt_required — the AJAX/fetch() side used by
        # upload/chat/session endpoints, not just full-page views.
        self.client.cookies[AUTH_COOKIE_NAME] = self._token_for("adminuser", "admin")
        response = self.client.post("/chat/", data=json.dumps({"question": "hi"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_regular_user_is_unaffected_on_chat_index(self):
        self.client.cookies[AUTH_COOKIE_NAME] = self._token_for("regularuser", "user")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
