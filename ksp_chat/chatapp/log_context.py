"""
log_context.py — request/connection-scoped context, visible to the logging
system without threading it through every function signature.

Individual logger.info(...) calls throughout the app don't structurally
carry "who triggered this, and as part of which request" — some mention a
username or session_key in the free-text message, most don't, and
framework-level logs (django.request, the ASGI access log) never do.
ContextVars set once per request/connection (by RequestContextLoggingMiddleware
and JWTAuthenticationMiddleware for HTTP, and their equivalents in
channels_auth.py/consumers.py for WebSockets) and read by
logging_handlers.RequestContextFilter tag every record automatically,
regardless of which module logs it, without touching each individual call
site.
"""

import contextlib
import logging
import time
from contextvars import ContextVar

current_username: ContextVar[str | None] = ContextVar("current_username", default=None)
current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)
current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)
current_correlation_id: ContextVar[str | None] = ContextVar("current_correlation_id", default=None)
current_endpoint: ContextVar[str | None] = ContextVar("current_endpoint", default=None)
current_method: ContextVar[str | None] = ContextVar("current_method", default=None)

# Sentinel for log records with no attributable user (app startup, a
# management command, anything outside a request). Never has a live-log
# destination — see logging_handlers.ChannelsLogHandler — and is filtered
# out of every per-user view of the log file, rather than shown to everyone
# or no one.
UNATTRIBUTED = "system"


def group_name_for(username: str) -> str:
    """The Channels group a given user's live log lines are broadcast to.
    Shared by logging_handlers.ChannelsLogHandler (sender) and
    consumers.LogConsumer (joiner) so the two can never drift apart."""
    return f"logs_{username}"


@contextlib.contextmanager
def log_timing(logger: logging.Logger, event_base: str, level: int = logging.INFO, **fields):
    """Times a block of code and logs `<event_base>_started` on entry, then
    `<event_base>_completed` (or `<event_base>_failed`, with the traceback,
    on an exception) on exit — both carrying duration_ms. Wraps call sites
    around the RAG pipeline's existing Strategy/Repository seams (extract,
    embed_*, query, generate) without needing to restructure those classes
    — they're already single-purpose methods, this just times the call.

    Yields a dict the caller can fill in with result-specific fields (e.g.
    chunk_count, results_count) to include on the *_completed line
    alongside duration_ms.
    """
    start = time.perf_counter()
    logger.log(level, "%s started", event_base, extra={"event": f"{event_base}_started", **fields})
    result_fields: dict = {}
    try:
        yield result_fields
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.exception(
            "%s failed", event_base,
            extra={"event": f"{event_base}_failed", "duration_ms": duration_ms, **fields},
        )
        raise
    else:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.log(
            level, "%s completed", event_base,
            extra={"event": f"{event_base}_completed", "duration_ms": duration_ms, **fields, **result_fields},
        )
