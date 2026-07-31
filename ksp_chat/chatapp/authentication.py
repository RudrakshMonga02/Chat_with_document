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
import logging

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# Cookie set by auth_views.login_view; read here and by JWTAuthenticationMiddleware.
AUTH_COOKIE_NAME = "auth_token"


def verify_jwt(token: str) -> str | None:
    """Decode and validate a token, returning the `sub` (username) claim.
    Returns None for anything invalid: bad signature, expired, malformed,
    or missing `sub` — also None if AUTH_JWT_SECRET_KEY isn't configured yet,
    so the app degrades to anonymous-only rather than erroring.

    AUTH_JWT_EXPECTED_ISS/AUD (settings.py) are optional and unset by
    default — the external auth service doesn't send `iss`/`aud` claims
    today, so passing None here (jose's own "skip this check" value) is a
    no-op until they're configured, at which point a token missing or
    mismatching either is rejected the same way an expired one is."""
    if not token or not settings.AUTH_JWT_SECRET_KEY:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.AUTH_JWT_SECRET_KEY,
            algorithms=[settings.AUTH_JWT_ALGORITHM],
            audience=settings.AUTH_JWT_EXPECTED_AUD or None,
            issuer=settings.AUTH_JWT_EXPECTED_ISS or None,
        )
    except JWTError as exc:
        # Never log the token itself — only that verification failed, and
        # why (expired vs. malformed vs. bad signature vs. — once AUD/ISS
        # are turned on — wrong audience/issuer all matter for telling "a
        # session naturally expired" apart from "someone is sending
        # tampered/foreign tokens"), a distinction that produced zero log
        # output before this.
        logger.warning(
            "JWT verification failed: %s", exc.__class__.__name__,
            extra={"event": "jwt_verification_failed", "reason": exc.__class__.__name__},
        )
        return None
    return payload.get("sub")


def extract_subject_id(token: str) -> str | None:
    """The immutable IdP-issued identifier claim, if this token carries one.
    The external auth service doesn't send this today — verify_jwt only
    ever sees `sub` used directly as the username — so this exists purely
    as groundwork: the moment a token does carry it, resolve_local_app_user
    starts preferring it over the mutable username as the real identity
    join key, with no other call site needing to change.

    Deliberately silent (returns None) on any decode failure — verify_jwt
    already logs that; this would just double-log the same failure. Only
    ever called after verify_jwt has already succeeded for this token, so
    in practice this decode always succeeds too."""
    if not token or not settings.AUTH_JWT_SECRET_KEY:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.AUTH_JWT_SECRET_KEY,
            algorithms=[settings.AUTH_JWT_ALGORITHM],
            audience=settings.AUTH_JWT_EXPECTED_AUD or None,
            issuer=settings.AUTH_JWT_EXPECTED_ISS or None,
        )
    except JWTError:
        return None
    return payload.get("subject_id") or payload.get("uid")


def get_request_username(request) -> str | None:
    """The authenticated username for this request, or None if anonymous.
    Populated on every request by JWTAuthenticationMiddleware. Already
    accounts for a local ban (see resolve_local_app_user) — this is never set
    for a banned user even though their token is still cryptographically
    valid, so every existing check against this function stays correct
    with zero changes."""
    return getattr(request, "jwt_username", None)


def resolve_local_app_user(username: str, subject_id: str | None = None):
    """The local AppUser row for this identity, or None if it's never been
    seen locally yet (e.g. a brand-new username whose first request just
    arrived). One query in the common case (subject_id absent — true for
    every request today, see extract_subject_id), shared by the ban check
    below and JWTAuthenticationMiddleware's user_id logging context rather
    than each looking it up separately.

    Prefers subject_id when given: it's the immutable IdP identifier, so a
    match on it is authoritative even if the username has since changed.
    Falls back to a username lookup exactly as before when it's absent —
    which, again, is every request until the IdP contract changes."""
    from .models import AppUser
    if subject_id:
        by_subject_id = AppUser.objects.filter(subject_id=subject_id).first()
        if by_subject_id is not None:
            return by_subject_id
    return AppUser.objects.filter(username=username).first()


def is_locally_active(username: str) -> bool:
    """Whether ksp_chat itself still honors this username, independent of
    whether the auth service still considers their token valid. The auth
    service is never told about this — an admin "removing" a user (see
    views.remove_user) only ever sets AppUser.is_active=False locally, so a
    banned person's still-unexpired token keeps authenticating fine against
    the auth service directly; this is the check that makes ksp_chat refuse
    it anyway. No local AppUser row at all just means "never banned" —
    covers a brand new username, and one whose row was deleted (a data
    wipe, a different action from banning) without ever being banned."""
    app_user = resolve_local_app_user(username)
    return app_user is None or app_user.is_active


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
