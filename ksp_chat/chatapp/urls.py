from django.urls import path
from . import auth_views, views

urlpatterns = [
    path("", views.index, name="index"),
    path("logs/", views.logs_page, name="logs"),
    path("upload/", views.upload_file, name="upload_file"),
    path("chat/", views.chat_api, name="chat_api"),
    path("new-session/", views.new_session, name="new_session"),
    path("load-session/<str:session_key>/", views.load_session, name="load_session"),
    path("delete-session/<str:session_key>/", views.delete_session, name="delete_session"),
    path("rename-session/<str:session_key>/", views.rename_session, name="rename_session"),
    path("remove-document/<int:document_id>/", views.remove_document, name="remove_document"),
    path("login/", auth_views.login_view, name="login"),
    path("register/", auth_views.register_view, name="register"),
    path("logout/", auth_views.logout_view, name="logout"),
]
