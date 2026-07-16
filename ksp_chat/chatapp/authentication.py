"""
authentication.py — local verification of JWTs issued by the external
FastAPI auth service (separate repo/process, see settings.AUTH_SERVICE_BASE_URL).

This app never handles a password. It only decodes and checks the
signature/expiry of tokens that service already issued, and trusts the
`sub` claim as the authenticated username — the standard "resource server"
side of a JWT split. No network call back to the auth service happens here;
see the plan notes on the introspection-vs-local-verification tradeoff
(local verification can't see a user deleted server-side until their
token naturally expires).
"""

import functools

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from jose import JWTError, jwt

# Cookie set by auth_views.login_view; read here and by JWTAuthenticationMiddleware.
AUTH_COOKIE_NAME = "auth_token"


def verify_jwt(token: str) -> str | None:
    """Decode and validate a token, returning the `sub` (username) claim.
    Returns None for anything invalid: bad signature, expired, malformed,
    or missing `sub` — also None if AUTH_JWT_SECRET_KEY isn't configured yet,
    so the app degrades to anonymous-only rather than erroring."""
    if not token or not settings.AUTH_JWT_SECRET_KEY:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.AUTH_JWT_SECRET_KEY,
            algorithms=[settings.AUTH_JWT_ALGORITHM],
        )
    except JWTError:
        return None
    return payload.get("sub")


def get_request_username(request) -> str | None:
    """The authenticated username for this request, or None if anonymous.
    Populated on every request by JWTAuthenticationMiddleware."""
    return getattr(request, "jwt_username", None)


def jwt_required(view_func):
    """View decorator for JSON/AJAX endpoints that must be authenticated.
    Returns a 401 JSON error (not a redirect) since every view using this
    is called via fetch() from chat.js — chat.js redirects to /login/ itself
    on a 401 (see handleAuthExpiry), which also covers a token expiring
    mid-session without a page reload."""

    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not get_request_username(request):
            return JsonResponse({"error": "Authentication required."}, status=401)
        return view_func(request, *args, **kwargs)

    return wrapper


def login_required(view_func):
    """View decorator for HTML page views that must be authenticated.
    Redirects to the login page rather than returning JSON — use jwt_required
    instead for endpoints called via fetch()."""

    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not get_request_username(request):
            return HttpResponseRedirect(reverse("login"))
        return view_func(request, *args, **kwargs)

    return wrapper
