"""
consumers.py — websocket consumer for the live /logs/ page.

Authorization mirrors login_required for the HTML page: any connection
without a valid JWT (see channels_auth.JWTAuthMiddleware, which populates
scope["jwt_username"]) is closed immediately. If settings.LOG_VIEWER_USERS
is non-empty, only usernames in that list may connect — that's a separate
concern from what happens after connecting, though: each connection joins
only *its own* user's Channels group (see log_context.group_name_for), so
regardless of who's allowed to open this page, nobody ever receives another
user's log lines.

connect()/disconnect() log their own websocket_connected/websocket_rejected/
websocket_disconnected events — there was previously no visibility at all
into who connected to (or was turned away from) the live log feed. One
nuance: those log calls run from inside an already-running async consumer
method, so if they reach the "live" handler (ChannelsLogHandler), its
async_to_sync call raises internally — caught by that handler's own blanket
except, so the line still lands in console/app.log, just never on the live
socket itself. See logging_handlers.py's module docstring for why.
"""

import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

from .log_context import current_request_id, current_username, group_name_for

logger = logging.getLogger(__name__)


class LogConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        username = self.scope.get("jwt_username")
        # Set directly, no reset-token/finally dance (unlike the HTTP
        # middleware): each websocket connection runs as its own asyncio
        # Task, and asyncio gives every Task its own copy of context from
        # the point it was created, so this can never leak into a
        # different connection's log records.
        current_username.set(username)
        current_request_id.set(self.scope.get("connection_id"))

        allowed = settings.LOG_VIEWER_USERS
        if not username or (allowed and username not in allowed):
            logger.warning(
                "Live log WebSocket rejected for '%s'", username or "anonymous",
                extra={"event": "websocket_rejected"},
            )
            await self.close()
            return
        self.group_name = group_name_for(username)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(
            "Live log WebSocket connected for '%s'", username,
            extra={"event": "websocket_connected"},
        )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(
            "Live log WebSocket disconnected (code %s)", close_code,
            extra={"event": "websocket_disconnected"},
        )

    async def log_message(self, event):
        await self.send(text_data=json.dumps(event["log"]))
