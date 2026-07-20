"""
channels_auth.py — websocket-scope equivalent of JWTAuthenticationMiddleware.

Django's HTTP MIDDLEWARE list (settings.py) never runs for websocket
connections — Channels uses its own, separate middleware stack (wired up in
asgi.py). This re-applies the exact same verify_jwt() check used for HTTP
requests, directly against the connection's cookies, rather than
reimplementing JWT verification a second time.
"""

from channels.middleware import BaseMiddleware
from channels.sessions import CookieMiddleware

from .authentication import AUTH_COOKIE_NAME, verify_jwt


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        token = scope.get("cookies", {}).get(AUTH_COOKIE_NAME)
        scope["jwt_username"] = verify_jwt(token) if token else None
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return CookieMiddleware(JWTAuthMiddleware(inner))
