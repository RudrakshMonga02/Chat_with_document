"""
URL configuration for ksp_chat project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('', include('chatapp.urls')),
]

# Gated behind DJANGO_ADMIN_ENABLED (see ksp_chat/settings.py): this is
# Django's own built-in admin site, a separate identity system from both
# this app's JWT auth and its own /users/ admin dashboard (chatapp/
# admin_auth.py). Off by default, so /admin/ returns a normal 404 unless
# explicitly opted into — it can never come alive just because a
# django.contrib.auth superuser happens to exist in the database.
if settings.DJANGO_ADMIN_ENABLED:
    urlpatterns.insert(0, path('admin/', admin.site.urls))
