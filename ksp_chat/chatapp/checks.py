"""
checks.py — Django system checks for authentication-related configuration
that today fails silently rather than loudly. Registered by being imported
from chatapp/apps.py's ready() (the `@register()` decorator does the actual
registration at import time). These are configuration-safety nets, not
authentication logic — `python manage.py check` (also run before `runserver`
and `migrate`) surfaces them.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def check_jwt_secret_configured(app_configs, **kwargs):
    """An unset AUTH_JWT_SECRET_KEY makes verify_jwt() (chatapp/
    authentication.py) reject every token — nobody can log in, but nothing
    says why; it just looks like the app is broken for everyone. Fine for
    local dev (DEBUG=True is documented to degrade to anonymous-only on
    purpose); a hard error once DEBUG=False, since that's the one setting a
    real deployment cannot have simply forgotten to configure."""
    if settings.DEBUG or settings.AUTH_JWT_SECRET_KEY:
        return []
    return [
        Error(
            "AUTH_JWT_SECRET_KEY is not set.",
            hint=(
                "With DEBUG=False, every request is treated as anonymous "
                "because verify_jwt() can never validate a token — set "
                "AUTH_JWT_SECRET_KEY to the same secret the external auth "
                "service signs tokens with."
            ),
            id="chatapp.E001",
        )
    ]


@register()
def check_django_admin_gate(app_configs, **kwargs):
    """DJANGO_ADMIN_ENABLED opts into a third identity system
    (django.contrib.auth's own User/is_staff/is_superuser) that this app's
    own code never otherwise uses — worth a loud reminder in production
    that /admin/'s access control is completely independent of both the
    JWT system and the app's own /users/ dashboard (chatapp/admin_auth.py)."""
    if settings.DEBUG or not settings.DJANGO_ADMIN_ENABLED:
        return []
    return [
        Warning(
            "DJANGO_ADMIN_ENABLED is on in a non-DEBUG deployment.",
            hint=(
                "/admin/ is reachable and gated only by django.contrib.auth's "
                "own User/is_staff/is_superuser — entirely separate from this "
                "app's JWT auth and its /users/ admin dashboard. Make sure "
                "that's a deliberate choice and that superuser accounts are "
                "managed carefully."
            ),
            id="chatapp.W001",
        )
    ]
