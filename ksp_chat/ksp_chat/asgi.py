"""
ASGI config for ksp_chat project.

It exposes the ASGI callable as a module-level variable named ``application``.

Regular HTTP traffic is still handled entirely by ``django_asgi_app`` below —
the same middleware stack, urls, and views as before. The only new territory
is the "websocket" branch, scoped to chatapp.routing.websocket_urlpatterns
(currently just the live /logs/ page).

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ksp_chat.settings')

# Must run before importing anything from chatapp below — it calls
# django.setup(), which the app registry needs to be ready for.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from chatapp.channels_auth import JWTAuthMiddlewareStack  # noqa: E402
from chatapp.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        JWTAuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
