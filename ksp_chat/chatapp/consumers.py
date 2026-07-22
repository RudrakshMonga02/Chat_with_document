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
"""

import json

from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

from .log_context import group_name_for


class LogConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        username = self.scope.get("jwt_username")
        allowed = settings.LOG_VIEWER_USERS
        if not username or (allowed and username not in allowed):
            await self.close()
            return
        self.group_name = group_name_for(username)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def log_message(self, event):
        await self.send(text_data=json.dumps(event["log"]))
