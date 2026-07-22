"""
auth_views.py — thin proxy to the external FastAPI JWT auth service.

This app never validates a password or stores one — register_view and
login_view forward credentials straight through to that service over a
server-to-server request and only handle the response. That service has no
CORS configured, so the browser can never call it directly; every request
has to go through here.
"""

import logging

import requests
from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .authentication import AUTH_COOKIE_NAME, get_request_username
from .models import AppUser

logger = logging.getLogger(__name__)

AUTH_REQUEST_TIMEOUT = 5  # seconds — a hung auth service shouldn't hang this app forever


@require_http_methods(["GET", "POST"])
def login_view(request):
    if get_request_username(request):
        return HttpResponseRedirect(reverse("index"))

    if request.method == "GET":
        return render(request, "chatapp/login.html", {})

    username = (request.POST.get("username") or "").strip()
    password = request.POST.get("password") or ""

    if not username or not password:
        return render(request, "chatapp/login.html", {"error": "Username and password are required."})

    try:
        resp = requests.post(
            f"{settings.AUTH_SERVICE_BASE_URL}/login",
            data={"username": username, "password": password},  # OAuth2PasswordRequestForm expects form encoding
            timeout=AUTH_REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        return render(request, "chatapp/login.html", {"error": "Auth service is unavailable — please try again shortly."})

    if resp.status_code != 200:
        logger.warning("Failed login attempt for username '%s'", username)
        return render(request, "chatapp/login.html", {"error": "Invalid username or password."})

    token = (resp.json() or {}).get("access_token")
    if not token:
        return render(request, "chatapp/login.html", {"error": "Unexpected response from the auth service."})

    # Ensures the AppUser shadow row exists as soon as someone logs in, not
    # just the first time they upload something (_get_or_create_chat_session
    # in views.py would also lazily create it, but there's no reason to wait).
    AppUser.objects.get_or_create(username=username)
    logger.info("User '%s' logged in", username)

    # Rotate the Django session on every login — without this, whatever
    # session_key this browser already had (e.g. left over from a previous
    # account on a shared browser) stays active, and _resolve_active_session_key
    # would resolve straight to that previous account's ChatSession. Matches
    # what django.contrib.auth's own login() does for the same reason, via
    # Django's session framework directly (no dependency on django.contrib.auth).
    request.session.flush()
    request.session.create()

    response = HttpResponseRedirect(reverse("index"))
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        httponly=True,
        samesite="Lax",
        secure=not settings.DEBUG,
        # Matches the auth service's own ACCESS_TOKEN_EXPIRE_MINUTES default;
        # this only bounds how long the cookie sticks around — the token's
        # own `exp` claim is what verify_jwt actually checks on each request.
        max_age=60 * 60,
    )
    return response


@require_http_methods(["GET", "POST"])
def register_view(request):
    if get_request_username(request):
        return HttpResponseRedirect(reverse("index"))

    if request.method == "GET":
        return render(request, "chatapp/register.html", {})

    username = (request.POST.get("username") or "").strip()
    password1 = request.POST.get("password1") or ""
    password2 = request.POST.get("password2") or ""

    errors = []
    if not username:
        errors.append("Username is required.")
    if not password1:
        errors.append("Password is required.")
    elif password1 != password2:
        errors.append("Passwords do not match.")

    if errors:
        return render(request, "chatapp/register.html", {"errors": errors})

    try:
        resp = requests.post(
            f"{settings.AUTH_SERVICE_BASE_URL}/register",
            json={"username": username, "password": password1},
            timeout=AUTH_REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        return render(request, "chatapp/register.html", {"errors": ["Auth service is unavailable — please try again shortly."]})

    if resp.status_code == 201:
        logger.info("New user registered: '%s'", username)
        return HttpResponseRedirect(reverse("login"))

    # Two different error shapes depending on failure: a 400 with a plain
    # string detail (e.g. duplicate username), or a 422 with a list of
    # Pydantic validation error objects (e.g. password too short).
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None

    if resp.status_code == 400 and isinstance(detail, str):
        errors = [detail]
    elif resp.status_code == 422 and isinstance(detail, list):
        errors = [d.get("msg", "Invalid input.") for d in detail]
    else:
        errors = ["Registration failed — please try again."]

    return render(request, "chatapp/register.html", {"errors": errors})


@require_http_methods(["POST"])
def logout_view(request):
    # Best-effort: revoke the token at the source (the auth service now
    # blacklists it) so it stops working everywhere, not just in this app.
    # If the auth service is unreachable, still log the user out locally —
    # this shouldn't be able to strand someone signed in.
    token = request.COOKIES.get(AUTH_COOKIE_NAME)
    if token:
        try:
            requests.post(
                f"{settings.AUTH_SERVICE_BASE_URL}/logout",
                headers={"Authorization": f"Bearer {token}"},
                timeout=AUTH_REQUEST_TIMEOUT,
            )
        except requests.RequestException:
            logger.warning("Failed to revoke token with the auth service on logout", exc_info=True)

    logger.info("User '%s' logged out", get_request_username(request))

    # Rotate the session here too, not just on login — an idle logged-out
    # browser shouldn't keep sitting on a session_key tied to whoever was
    # just using it, waiting for the next login to clean it up.
    request.session.flush()
    request.session.create()

    response = HttpResponseRedirect(reverse("login"))
    response.delete_cookie(AUTH_COOKIE_NAME)
    return response
