"""
middleware.py — two request-scoped concerns, deliberately kept in separate
middleware classes:

  JWTAuthenticationMiddleware     — resolves *who* is calling (unchanged
                                    responsibility from before).
  RequestContextLoggingMiddleware — resolves *how to trace* the call: a
                                    request id, an inbound/propagated
                                    correlation id, and request_started/
                                    request_completed logging. Listed first
                                    in settings.MIDDLEWARE so a request id
                                    exists before anything downstream —
                                    including auth resolution — logs
                                    anything.

JWTAuthenticationMiddleware reads the auth cookie set by auth_views.login_view
and verifies it locally (chatapp.authentication.verify_jwt). Never blocks a
request itself — login_required/jwt_required (chatapp.authentication) are
what actually enforce it on views that need it.

It also enforces the local ban check — a cryptographically valid token for
a locally-banned username is treated exactly like no token at all,
request.jwt_username stays None, and every existing login_required/
jwt_required check downstream keeps working unchanged. The auth service is
never consulted or informed; see authentication.py. The AppUser lookup
this needs (resolve_local_app_user) is done once and reused for both the
ban check and the user_id published below — not two separate queries.

Both middleware publish their context (username/user_id here; request_id/
correlation_id/endpoint/method in RequestContextLoggingMiddleware) to
log_context's ContextVars for the duration of the request, so every log
record produced while handling it — regardless of which module logs it —
can be attributed correctly (see settings.LOGGING's RequestContextFilter,
and the live /logs/ page).
"""

import logging
import time
import uuid

from .authentication import AUTH_COOKIE_NAME, extract_role, extract_subject_id, resolve_local_app_user, verify_jwt
from .log_context import (
    current_correlation_id,
    current_endpoint,
    current_method,
    current_request_id,
    current_user_id,
    current_username,
)

request_logger = logging.getLogger("chatapp.request")

# The django.test.Client / most reverse proxies expose a custom request
# header "X-Correlation-ID" as this META key.
CORRELATION_ID_HEADER = "HTTP_X_CORRELATION_ID"


class JWTAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.COOKIES.get(AUTH_COOKIE_NAME)
        username = verify_jwt(token) if token else None
        # Only worth decoding again for subject_id/role when the first
        # decode already succeeded — an invalid/absent token needs no
        # second look.
        subject_id = extract_subject_id(token) if username else None
        role = extract_role(token) if username else None

        app_user = resolve_local_app_user(username, subject_id) if username else None
        if username and app_user is not None and not app_user.is_active:
            username = None
        request.jwt_username = username
        request.jwt_role = role
        # Plain request attributes, not just the ContextVars set below —
        # RequestContextLoggingMiddleware wraps this middleware (see its own
        # docstring for why) and logs request_completed only after
        # get_response() returns, by which point this middleware's own
        # `finally` block below has already reset the ContextVars back to
        # their prior value. request.jwt_username/jwt_user_id survive that
        # reset (they're plain attributes on the shared request object, not
        # context-local state), so that one log line can read the real
        # values directly instead of picking up whatever the ContextVar
        # already reset to.
        request.jwt_user_id = app_user.id if (username and app_user is not None) else None

        # Self-heal the local AppUser.role shadow from the JWT on every
        # request — same pattern as the ban check above, so a role change
        # on the auth service side is reflected here without a separate
        # sync step, once this user's token/requests catch up.
        if username and app_user is not None and app_user.role != role:
            app_user.role = role
            app_user.save(update_fields=["role"])

        username_token = current_username.set(username)
        # Only meaningful when username survived the ban check above — a
        # banned/anonymous request has no AppUser to attribute logs to.
        user_id_token = current_user_id.set(
            app_user.id if (username and app_user is not None) else None
        )
        try:
            return self.get_response(request)
        finally:
            current_username.reset(username_token)
            current_user_id.reset(user_id_token)


class RequestContextLoggingMiddleware:
    """Generates a request id for every HTTP request, and reuses/propagates
    an inbound X-Correlation-ID header so a request that calls out to (or
    was itself triggered by) the external FastAPI auth service can be
    traced across both services' logs under one shared id (see
    auth_views.py, which forwards it on its outbound requests.post calls).
    Logs request_started/request_completed with method, path, status, and
    duration — request-lifecycle logging that didn't exist before.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = uuid.uuid4().hex
        correlation_id = request.META.get(CORRELATION_ID_HEADER) or request_id
        request.request_id = request_id
        request.correlation_id = correlation_id

        req_token = current_request_id.set(request_id)
        corr_token = current_correlation_id.set(correlation_id)
        endpoint_token = current_endpoint.set(request.path)
        method_token = current_method.set(request.method)

        start = time.perf_counter()
        request_logger.info(
            "%s %s", request.method, request.path,
            extra={"event": "request_started"},
        )
        try:
            response = self.get_response(request)
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            request_logger.info(
                "%s %s -> %s (%.1fms)", request.method, request.path, response.status_code, duration_ms,
                extra={
                    "event": "request_completed",
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "username": getattr(request, "jwt_username", None),
                    "user_id": getattr(request, "jwt_user_id", None),
                },
            )
            return response
        finally:
            current_request_id.reset(req_token)
            current_correlation_id.reset(corr_token)
            current_endpoint.reset(endpoint_token)
            current_method.reset(method_token)
