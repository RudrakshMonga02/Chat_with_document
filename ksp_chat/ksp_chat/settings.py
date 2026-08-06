"""
Django settings for ksp_chat project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load variables from a .env file placed next to manage.py
load_dotenv(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
# Falls back to the original dev-only key so local behavior is unchanged;
# set DJANGO_SECRET_KEY in .env for any non-local deployment.
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-vko9%3t0di(r^&@7#)zkc*+j7@!%wc+e9b&=10=b&g%riu38_=',
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h.strip()
]

# The API gateway (api-gateway/, a separate process) forwards requests here
# from its own address — the browser's Origin header says the gateway's
# origin (e.g. http://127.0.0.1:8081), but this process's own host:port is
# whatever it's actually bound to (e.g. 127.0.0.1:8000). Django's CSRF
# middleware checks the Origin header against request.get_host() for every
# POST/PUT/PATCH/DELETE and rejects a mismatch — without this, that's every
# such request a real browser sends through the gateway (login, logout,
# create-user, rename/delete session, ...), since curl/requests-based
# testing never sends an Origin header and so never exercises this check at
# all. Comma-separated so a deployment behind a different gateway origin can
# override it without a code change.
#
# The gateway's default is 8081, not 8080 — something on this machine
# (never identified; likely security/proxy software) transparently
# intercepts port 8080 and serves stale responses that never reflect a
# running process's real code, regardless of restarts. See api-gateway's
# own README for how this was diagnosed.
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', 'http://127.0.0.1:8081').split(',') if o.strip()
]

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'chatapp',
]

MIDDLEWARE = [
    # First/outermost so the request id + timing it sets up covers the
    # entire request, including the auth/session/CSRF middleware below it —
    # see chatapp.middleware.RequestContextLoggingMiddleware's own docstring.
    'chatapp.middleware.RequestContextLoggingMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'chatapp.middleware.JWTAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ksp_chat.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ksp_chat.wsgi.application'
# Regular HTTP traffic still goes through WSGI/the app above unchanged;
# ASGI is only what the live /logs/ websocket route (chatapp/routing.py)
# needs, wired up in asgi.py.
ASGI_APPLICATION = 'ksp_chat.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ChromaDB persistence directory
CHROMA_PERSIST_DIR = str(BASE_DIR / 'chroma_db')

# Gemini API key — loaded from .env file above, never hardcoded
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

# External FastAPI JWT auth service (separate repo/process — this app never
# handles passwords itself, only verifies tokens it issues). SECRET_KEY/
# ALGORITHM must match that service's own .env exactly, or every token will
# fail local verification. Deliberately named apart from Django's own
# SECRET_KEY above so the two can never be confused/collide.
# Left unset, login/register/logout simply won't work yet — the rest of the
# app (anonymous, session-based) is unaffected.
AUTH_JWT_SECRET_KEY = os.environ.get('AUTH_JWT_SECRET_KEY', '')
AUTH_JWT_ALGORITHM = os.environ.get('AUTH_JWT_ALGORITHM', 'HS256')
AUTH_SERVICE_BASE_URL = os.environ.get('AUTH_SERVICE_BASE_URL', 'http://127.0.0.1:8001')
# Optional hardening, both unset (skipped) by default: the external auth
# service doesn't send `iss`/`aud` claims today (only `sub`), so turning
# these on before it does would lock everyone out. Once it's confirmed to
# set them, set the matching value here and chatapp.authentication.verify_jwt
# will start rejecting any token not meant for this app specifically.
AUTH_JWT_EXPECTED_ISS = os.environ.get('AUTH_JWT_EXPECTED_ISS', '')
AUTH_JWT_EXPECTED_AUD = os.environ.get('AUTH_JWT_EXPECTED_AUD', '')

# Django's own built-in admin site (/admin/, django.contrib.admin) is a
# THIRD identity system alongside the two above — django.contrib.auth's own
# User/is_staff/is_superuser, which nothing else in this app ever reads
# (no code here touches request.user). Off by default so it can never
# become reachable just because a superuser happens to exist in the DB —
# see ksp_chat/urls.py, which only registers the /admin/ URL when this is
# True, and chatapp/checks.py, which warns if it's on outside DEBUG.
DJANGO_ADMIN_ENABLED = os.environ.get('DJANGO_ADMIN_ENABLED', 'False') == 'True'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Channels layer backing the live /logs/ page. In-memory is fine for a
# single dev process; a production deployment running multiple worker
# processes needs channels_redis instead, since InMemoryChannelLayer
# doesn't share group membership across processes.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# Usernames allowed to open the live logs page/socket (see chatapp/consumers.py).
# Empty (default) means any authenticated user can view — set
# LOG_VIEWER_USERS="alice,bob" in .env to restrict it.
LOG_VIEWER_USERS = [
    u.strip() for u in os.environ.get('LOG_VIEWER_USERS', '').split(',') if u.strip()
]

(BASE_DIR / "logs").mkdir(exist_ok=True)

# Env-driven rather than hardcoded, so a deployment can turn chatapp's
# logger up/down without editing this file. Defaults mirror DEBUG: verbose
# locally, quieter (but still fully event-tagged) everywhere else.
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'DEBUG' if DEBUG else 'INFO')
# Only controls the "console" handler below — a human-readable line for
# whoever is tailing a terminal in dev, or "json" for a deployment whose log
# aggregator scrapes stdout. The "file" handler (app.log) always uses JSON
# regardless of this setting: it's the one views._read_recent_logs parses
# back out directly to seed the live /logs/ page's history, and a stable
# structured format is what makes that safe without regex-matching text.
LOG_FORMAT = os.environ.get('LOG_FORMAT', 'text' if DEBUG else 'json')

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} [{username}] {name} {message}", "style": "{"},
        "json": {"()": "chatapp.logging_handlers.JSONFormatter"},
    },
    "filters": {
        "request_context": {"()": "chatapp.logging_handlers.RequestContextFilter"},
    },
    "handlers": {
        # The filter has to live on each handler, not the "django"/"chatapp"
        # logger entries below — nearly every logger.getLogger(__name__) call
        # in this app (e.g. "chatapp.views") is a *child* of "chatapp", and
        # Logger.callHandlers() walks straight to an ancestor's handlers on
        # propagation without re-running the ancestor logger's own filters.
        # A filter on the logger only ever applies to records logged
        # directly against that exact logger name.
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if LOG_FORMAT == "json" else "verbose",
            "filters": ["request_context"],
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "app.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "json",
            "filters": ["request_context"],
        },
        # Feeds the live /logs/ page — see chatapp/logging_handlers.py for
        # why this can never block/slow down the request that logged. Its
        # own emit() builds the payload from the record's structured fields
        # directly, so the "formatter" here is unused but harmless.
        "live": {
            "class": "chatapp.logging_handlers.ChannelsLogHandler",
            "formatter": "json",
            "filters": ["request_context"],
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console", "file", "live"], "level": "INFO", "propagate": False},
        "chatapp": {"handlers": ["console", "file", "live"], "level": LOG_LEVEL, "propagate": False},
    },
}
