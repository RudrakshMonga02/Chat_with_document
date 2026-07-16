"""
middleware.py — attaches request.jwt_username on every request.

Reads the auth cookie set by auth_views.login_view and verifies it locally
(chatapp.authentication.verify_jwt). Never blocks a request itself — this
app's core features stay usable anonymously by design (login is optional,
layered on top of the existing session-key-based flow, not a replacement
for it). Views that must require login use the jwt_required decorator.
"""

from .authentication import AUTH_COOKIE_NAME, verify_jwt


class JWTAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.COOKIES.get(AUTH_COOKIE_NAME)
        request.jwt_username = verify_jwt(token) if token else None
        return self.get_response(request)
