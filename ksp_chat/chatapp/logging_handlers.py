"""
logging_handlers.py — feeds the live /logs/ page over the "logs" Channels
group, using the standard Channels pattern: call
async_to_sync(channel_layer.group_send) directly from sync logging code.

An earlier version of this ran the send on a separate background thread to
guarantee emit() could never block. That turned out to be actively wrong:
InMemoryChannelLayer keeps a per-channel asyncio.Queue that binds to
whichever event loop first touches it, and a group_send issued from an
unrelated thread's own event loop can't safely wake a consumer waiting on a
different loop — messages were silently never delivered. Calling
async_to_sync directly (no extra thread) works correctly instead, because
asgiref recognizes the ambient loop of the ASGI server (Daphne) when the
call happens on a thread Daphne itself dispatched the request to — the
same loop the websocket consumers run on.

The trade-off: emit() can now briefly block on the channel layer. Kept
acceptable by (a) only wiring this handler to chatapp/django loggers, not
every library logger, and (b) swallowing all exceptions, so a broken or
slow channel layer degrades to a dropped live-log line, never an error or
hang that affects the code that logged.
"""

import logging

from asgiref.sync import async_to_sync


class ChannelsLogHandler(logging.Handler):
    def emit(self, record):
        # Imported lazily: Django parses LOGGING (instantiating this handler)
        # before the app registry finishes populating.
        from channels.layers import get_channel_layer

        try:
            channel_layer = get_channel_layer()
            if channel_layer is None:
                return
            payload = {
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
                "time": record.created,
            }
            async_to_sync(channel_layer.group_send)(
                "logs", {"type": "log.message", "log": payload}
            )
        except Exception:
            pass  # a broken/slow channel layer must never affect logging itself
