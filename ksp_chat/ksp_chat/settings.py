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

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'chatapp',
]

MIDDLEWARE = [
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

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
