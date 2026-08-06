"""
admin_views.py — the admin area: a small, standalone dashboard for viewing
registered AppUser accounts, creating new ones, and removing one.

Deliberately separate from views.py — the admin UI (its own nav bar, no
sidebar/chat chrome) is a genuinely different surface, not a page bolted
onto the chat app. Admin identity itself (admin_auth.py) is the same
JWT/AppUser system as everywhere else, gated by an added role check.
"""

import json
import logging

import requests
from django.conf import settings
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .admin_auth import admin_page_required, admin_required
from .authentication import AUTH_COOKIE_NAME
from .auth_views import _correlation_headers, AUTH_REQUEST_TIMEOUT
from .models import AppUser, ChatSession

logger = logging.getLogger(__name__)


@admin_page_required
def admin_users_page(request):
    users = list(
        AppUser.objects.all()
        .order_by("username")
        .values("username", "role", "is_active", "created_at")
    )
    counts = dict(
        ChatSession.objects.exclude(owner__isnull=True)
        .values_list("owner__username")
        .annotate(n=Count("id"))
        .values_list("owner__username", "n")
    )
    for u in users:
        u["chat_session_count"] = counts.get(u["username"], 0)

    return render(request, "chatapp/admin_users.html", {"users": users})


@require_http_methods(["POST"])
@admin_required
def create_user(request):
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        return JsonResponse({"error": "Username and password are required."}, status=400)

    # No role in the payload, deliberately — an admin can only create plain
    # users this way, never another admin. The auth service's /admin/users
    # enforces this too (schemas.AdminUserCreate has no role field at all),
    # so this isn't just a UI-level restriction.
    token = request.COOKIES.get(AUTH_COOKIE_NAME)
    try:
        resp = requests.post(
            f"{settings.AUTH_SERVICE_BASE_URL}/admin/users",
            json={"username": username, "password": password},
            headers={"Authorization": f"Bearer {token}", **_correlation_headers()},
            timeout=AUTH_REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        return JsonResponse({"error": "Auth service is unavailable — please try again shortly."}, status=502)

    if resp.status_code == 201:
        # Local shadow row created eagerly so the new account shows up in
        # the dashboard immediately, before it's ever logged in itself —
        # see models.AppUser's role field docstring.
        AppUser.objects.update_or_create(username=username, defaults={"role": AppUser.ROLE_USER, "is_active": True})
        logger.info(
            "Admin created user '%s'", username,
            extra={"event": "admin_user_created", "role": AppUser.ROLE_USER},
        )
        counts = dict(
            ChatSession.objects.exclude(owner__isnull=True)
            .values_list("owner__username")
            .annotate(n=Count("id"))
            .values_list("owner__username", "n")
        )
        return JsonResponse({
            "username": username,
            "role": AppUser.ROLE_USER,
            "is_active": True,
            "chat_session_count": counts.get(username, 0),
        }, status=201)

    # Same two error shapes as auth_views.register_view: a 400 with a plain
    # string detail (duplicate username), or a 422 with a list of Pydantic
    # validation error objects.
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None

    if resp.status_code == 400 and isinstance(detail, str):
        error = detail
    elif resp.status_code == 422 and isinstance(detail, list):
        error = "; ".join(d.get("msg", "Invalid input.") for d in detail)
    elif resp.status_code == 403:
        error = "Admin access required."
    else:
        error = "Failed to create user — please try again."

    return JsonResponse({"error": error}, status=resp.status_code if resp.status_code in (400, 403, 422) else 502)


@require_http_methods(["DELETE"])
@admin_required
def remove_user(request, username):
    try:
        target = AppUser.objects.get(username=username)
    except AppUser.DoesNotExist:
        return JsonResponse({"error": "User not found."}, status=404)

    # Ban locally — the auth service isn't told and still considers their
    # token valid; JWTAuthenticationMiddleware is what actually refuses it
    # from here on (see authentication.is_locally_active).
    target.is_active = False
    target.save(update_fields=["is_active"])

    # ChatSession.owner uses SET_NULL specifically so deleting an AppUser
    # alone never destroys chat history — "removing a user" here means
    # actually clearing their data too, not just banning + orphaning it.
    ChatSession.objects.filter(owner=target).delete()

    logger.info(
        "Admin removed user '%s'", username,
        extra={"event": "admin_user_removed"},
    )

    return JsonResponse({"removed": username})
