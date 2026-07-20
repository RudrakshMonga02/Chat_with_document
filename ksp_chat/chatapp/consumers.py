"""
consumers.py — websocket consumer for the live /logs/ page.

Authorization mirrors login_required for the HTML page: any connection
without a valid JWT (see channels_auth.JWTAuthMiddleware, which populates
scope["jwt_username"]) is closed immediately. If settings.LOG_VIEWER_USERS
is non-empty, only usernames in that list may connect.
"""

import json

from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

GROUP_NAME = "logs"


class LogConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        username = self.scope.get("jwt_username")
        allowed = settings.LOG_VIEWER_USERS
        if not username or (allowed and username not in allowed):
            await self.close()
            return
        await self.channel_layer.group_add(GROUP_NAME, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP_NAME, self.channel_name)

    async def log_message(self, event):
        await self.send(text_data=json.dumps(event["log"]))
