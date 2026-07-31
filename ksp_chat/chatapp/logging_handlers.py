"""
logging_handlers.py — structured logging support for chatapp:

  RequestContextFilter — tags every record with the request/connection-
                         scoped context set by RequestContextLoggingMiddleware
                         (chatapp/middleware.py) and its WebSocket-scope
                         equivalent (chatapp/channels_auth.py,
                         chatapp/consumers.py): username, request id,
                         correlation id, user id, endpoint, method.

  JSONFormatter        — one JSON object per log line. Used unconditionally
                         for the "file" handler (app.log) — see
                         settings.LOGGING — since views._read_recent_logs
                         parses that file back out directly to seed the
                         live /logs/ page's history, and a stable structured
                         format is what makes that safe to do without
                         regex-matching a human-oriented text format.

  ChannelsLogHandler   — feeds the live /logs/ page over a per-user Channels
                         group, using the standard Channels pattern: call
                         async_to_sync(channel_layer.group_send) directly
                         from sync logging code.

An earlier version of ChannelsLogHandler ran the send on a separate
background thread to guarantee emit() could never block. That turned out to
be actively wrong: InMemoryChannelLayer keeps a per-channel asyncio.Queue
that binds to whichever event loop first touches it, and a group_send
issued from an unrelated thread's own event loop can't safely wake a
consumer waiting on a different loop — messages were silently never
delivered. Calling async_to_sync directly (no extra thread) works correctly
instead, because asgiref recognizes the ambient loop of the ASGI server
(Daphne) when the call happens on a thread Daphne itself dispatched the
request to — the same loop the websocket consumers run on.

The trade-off: emit() can now briefly block on the channel layer. Kept
acceptable by (a) only wiring this handler to chatapp/django loggers, not
every library logger, and (b) swallowing all exceptions, so a broken or
slow channel layer degrades to a dropped live-log line, never an error or
hang that affects the code that logged. One consequence worth knowing: a
log call made from *inside* an async consumer (chatapp/consumers.py) is
already running on the event loop, so async_to_sync there raises "cannot
use AsyncToSync in the same thread as an async event loop" — caught by the
same blanket except below, so it degrades the same way (the line still
reaches the console/file handlers, just never the live socket).
"""

import json
import logging
import re

from asgiref.sync import async_to_sync

from .log_context import (
    UNATTRIBUTED,
    current_correlation_id,
    current_endpoint,
    current_method,
    current_request_id,
    current_user_id,
    current_username,
    group_name_for,
)

# Daphne colorizes its own access-log messages (e.g. "django.channels.server")
# with raw ANSI escape codes before they ever reach this formatter/handler,
# so they'd otherwise end up baked into stored/displayed log text. Stripped
# once here, at write time, rather than downstream at read time.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _clean_message(record: logging.LogRecord) -> str:
    return _ANSI_RE.sub("", record.getMessage())


class RequestContextFilter(logging.Filter):
    """Tags every record with who/what produced it: the username set by
    JWTAuthenticationMiddleware, and the request id / correlation id / user
    id / endpoint / method set by RequestContextLoggingMiddleware (or their
    WebSocket-scope equivalents in channels_auth.py/consumers.py). Attached
    to each handler, not the "django"/"chatapp" logger entries in
    settings.LOGGING — nearly every logger.getLogger(__name__) call in this
    app (e.g. "chatapp.views") is a *child* of "chatapp", and
    Logger.callHandlers() walks straight to an ancestor's handlers on
    propagation without re-running the ancestor logger's own filters. A
    filter on the logger only ever applies to records logged directly
    against that exact logger name."""

    def filter(self, record):
        record.username = current_username.get() or UNATTRIBUTED
        record.request_id = current_request_id.get()
        record.correlation_id = current_correlation_id.get()
        record.user_id = current_user_id.get()
        record.endpoint = current_endpoint.get()
        record.method = current_method.get()
        return True


class JSONFormatter(logging.Formatter):
    """One JSON object per line. Carries the same context RequestContextFilter
    attaches, plus whatever event-specific extra= fields a call site passed
    (duration_ms, chunk_count, top_k, status_code, ...) — those flow through
    automatically rather than needing to be named here."""

    # LogRecord's own built-in attribute names, so the loop below only picks
    # up genuinely custom extra= fields, not internals like `msg`/`args`.
    _RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()) | {
        "message", "asctime",
    }

    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "timestamp_epoch": record.created,
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", None),
            "message": _clean_message(record),
            "request_id": getattr(record, "request_id", None),
            "correlation_id": getattr(record, "correlation_id", None),
            "username": getattr(record, "username", None),
            "user_id": getattr(record, "user_id", None),
            "endpoint": getattr(record, "endpoint", None),
            "method": getattr(record, "method", None),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ChannelsLogHandler(logging.Handler):
    def emit(self, record):
        username = getattr(record, "username", None)
        if not username or username == UNATTRIBUTED:
            return  # no attributable user — nowhere to send it, see UNATTRIBUTED

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
                "event": getattr(record, "event", None),
                "message": _clean_message(record),
                "time": record.created,
                "request_id": getattr(record, "request_id", None),
                "duration_ms": getattr(record, "duration_ms", None),
            }
            async_to_sync(channel_layer.group_send)(
                group_name_for(username), {"type": "log.message", "log": payload}
            )
        except Exception:
            pass  # a broken/slow channel layer must never affect logging itself
