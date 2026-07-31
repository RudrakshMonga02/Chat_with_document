"""
channels_auth.py — websocket-scope equivalent of JWTAuthenticationMiddleware,
including the same local ban check: a locally-banned user's still-valid JWT
is refused here exactly like it is for HTTP requests (see
authentication.is_locally_active) — this used to skip that check entirely,
so a banned user's live-log WebSocket connection kept working after an HTTP
request from the same account would already be treated as anonymous.

Also assigns a per-connection id (the websocket-scope equivalent of
RequestContextLoggingMiddleware's request id).

Django's HTTP MIDDLEWARE list (settings.py) never runs for websocket
connections — Channels uses its own, separate middleware stack (wired up in
asgi.py). This re-applies the exact same verify_jwt() check used for HTTP
requests, directly against the connection's cookies, rather than
reimplementing JWT verification a second time.
"""

import uuid

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from channels.sessions import CookieMiddleware

from .authentication import AUTH_COOKIE_NAME, is_locally_active, verify_jwt


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        token = scope.get("cookies", {}).get(AUTH_COOKIE_NAME)
        username = verify_jwt(token) if token else None
        # is_locally_active does a synchronous ORM query — Channels'
        # database_sync_to_async is the standard way to call that safely
        # from this async middleware, same helper the HTTP-side
        # JWTAuthenticationMiddleware uses directly (it's already sync).
        if username and not await database_sync_to_async(is_locally_active)(username):
            username = None
        scope["jwt_username"] = username
        scope["connection_id"] = uuid.uuid4().hex
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return CookieMiddleware(JWTAuthMiddleware(inner))
