from django.apps import AppConfig


class ChatappConfig(AppConfig):
    name = 'chatapp'

    def ready(self):
        from . import signals  # noqa: F401
        from . import checks  # noqa: F401 — registers system checks on import
