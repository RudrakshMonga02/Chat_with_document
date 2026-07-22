"""
log_context.py — request-scoped username, visible to the logging system.

Individual logger.info(...) calls throughout the app don't structurally
carry "who triggered this" — some mention a username or session_key in the
free-text message, most don't, and framework-level logs (django.request,
the ASGI access log) never do. A ContextVar set once per request by
JWTAuthenticationMiddleware and read by UsernameLogFilter (see
settings.LOGGING) tags every record automatically, regardless of which
module logs it, without touching each individual call site.
"""

from contextvars import ContextVar

current_username: ContextVar[str | None] = ContextVar("current_username", default=None)

# Sentinel for log records with no attributable user (app startup, a
# management command, anything outside a request). Never has a live-log
# destination — see ChannelsLogHandler — and is filtered out of every
# per-user view of the log file, rather than shown to everyone or no one.
UNATTRIBUTED = "system"


def group_name_for(username: str) -> str:
    """The Channels group a given user's live log lines are broadcast to.
    Shared by logging_handlers.ChannelsLogHandler (sender) and
    consumers.LogConsumer (joiner) so the two can never drift apart."""
    return f"logs_{username}"
