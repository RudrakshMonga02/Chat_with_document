from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("upload/", views.upload_file, name="upload_file"),
    path("chat/", views.chat_api, name="chat_api"),
    path("new-session/", views.new_session, name="new_session"),
    path("load-session/<str:session_key>/", views.load_session, name="load_session"),
    path("delete-session/<str:session_key>/", views.delete_session, name="delete_session"),
    path("remove-document/<int:document_id>/", views.remove_document, name="remove_document"),
]
