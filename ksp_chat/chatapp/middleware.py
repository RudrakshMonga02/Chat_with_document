"""
middleware.py — attaches request.jwt_username on every request.

Reads the auth cookie set by auth_views.login_view and verifies it locally
(chatapp.authentication.verify_jwt). Never blocks a request itself —
login_required/jwt_required (chatapp.authentication) are what actually
enforce it on views that need it.

Also publishes the resolved username to log_context.current_username for
the duration of the request, so every log record produced while handling
it — regardless of which module logs it — can be attributed to the right
user (see settings.LOGGING's UsernameLogFilter, and the live /logs/ page).
"""

from .authentication import AUTH_COOKIE_NAME, verify_jwt
from .log_context import current_username


class JWTAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.COOKIES.get(AUTH_COOKIE_NAME)
        request.jwt_username = verify_jwt(token) if token else None

        reset_token = current_username.set(request.jwt_username)
        try:
            return self.get_response(request)
        finally:
            current_username.reset(reset_token)
