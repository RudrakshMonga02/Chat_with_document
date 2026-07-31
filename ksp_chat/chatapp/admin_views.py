"""
admin_views.py — the admin area: a small, standalone dashboard with no
overlap with the chat app. Its only capability today is viewing registered
AppUser accounts and removing one.

Deliberately separate from views.py/auth_views.py — admin identity
(admin_auth.py) has nothing to do with the JWT/AppUser system those use,
and the admin UI (its own nav bar, no sidebar/chat chrome) is a genuinely
different surface, not a page bolted onto the chat app.
"""

import logging

from django.db.models import Count
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .admin_auth import ADMIN_SESSION_KEY, admin_page_required, admin_required
from .models import AppUser, ChatSession

logger = logging.getLogger(__name__)


@admin_page_required
def admin_users_page(request):
    users = list(
        AppUser.objects.all()
        .order_by("username")
        .values("username", "is_active", "created_at")
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


@require_http_methods(["POST"])
def admin_logout_view(request):
    request.session.pop(ADMIN_SESSION_KEY, None)
    request.session.flush()
    request.session.create()
    return HttpResponseRedirect(reverse("login"))
