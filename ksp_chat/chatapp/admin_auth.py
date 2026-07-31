"""
admin_auth.py — authentication for the admin area, deliberately independent
from authentication.py's JWT-based user auth.

There is exactly one admin identity: a hardcoded username/password
(settings.ADMIN_USERNAME/ADMIN_PASSWORD), checked with a plain comparison.
It is never issued by the external auth service, never tied to an AppUser
row, and never created through registration — admin access is granted by
whoever configures those two settings, not by anything self-service.

An admin session is tracked with a plain flag in Django's own session
framework (request.session), the same mechanism this app already uses for
session_key/ChatSession — not a JWT, not a cookie of its own. There's one
admin identity, not a table of them, so there's nothing to look up on each
request beyond "is this flag set."
"""

import functools
import hmac

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse

ADMIN_SESSION_KEY = "is_admin"


def check_admin_credentials(username: str, password: str) -> bool:
    """True only if both settings are configured AND match exactly. Always
    False if either is left unset, so a misconfigured/fresh deployment
    can't be logged into with a blank username/password.

    Uses hmac.compare_digest (constant-time) rather than == — this is the
    one login form on the whole site checked against a fixed value instead
    of anything hashed/rate-limited, so it's worth not leaking match-length
    information through a fast-fail string comparison, even though the
    single-operator deployment model here makes that a low-severity gap."""
    if not settings.ADMIN_USERNAME or not settings.ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(
        username.encode("utf-8"), settings.ADMIN_USERNAME.encode("utf-8")
    ) and hmac.compare_digest(
        password.encode("utf-8"), settings.ADMIN_PASSWORD.encode("utf-8")
    )


def is_admin_request(request) -> bool:
    return bool(request.session.get(ADMIN_SESSION_KEY))


def admin_required(view_func):
    """JSON/AJAX version — for the remove-user endpoint."""

    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_admin_request(request):
            return JsonResponse({"error": "Admin authentication required."}, status=401)
        return view_func(request, *args, **kwargs)

    return wrapper


def admin_page_required(view_func):
    """Page version — for the admin dashboard. Redirects to the shared
    /login/ page (not a separate admin login route — the role choice lives
    on that one form) rather than showing an error page."""

    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_admin_request(request):
            return HttpResponseRedirect(reverse("login"))
        return view_func(request, *args, **kwargs)

    return wrapper
