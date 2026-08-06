"""
admin_auth.py — access control for the admin area.

Admin is now a real role on a real JWT-authenticated AppUser account (the
`role` claim, issued by the external auth service, verified the same way
as any other request — see chatapp/authentication.py and middleware.py).
There is no longer a separate hardcoded admin identity or session flag:
`admin_required`/`admin_page_required` below just add a role check on top
of the same authentication every other view already uses.
"""

import functools

from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse

from .authentication import get_request_role, get_request_username


def is_admin_request(request) -> bool:
    return bool(get_request_username(request)) and get_request_role(request) == "admin"


def admin_required(view_func):
    """JSON/AJAX version — for the admin-only API endpoints."""

    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_admin_request(request):
            return JsonResponse({"error": "Admin authentication required."}, status=401)
        return view_func(request, *args, **kwargs)

    return wrapper


def admin_page_required(view_func):
    """Page version — for the admin dashboard. An anonymous request is sent
    to the shared /login/ page; an authenticated-but-non-admin one is sent
    to the regular chat index rather than back to /login/, which would
    otherwise loop since they're already logged in."""

    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not get_request_username(request):
            return HttpResponseRedirect(reverse("login"))
        if get_request_role(request) != "admin":
            return HttpResponseRedirect(reverse("index"))
        return view_func(request, *args, **kwargs)

    return wrapper
