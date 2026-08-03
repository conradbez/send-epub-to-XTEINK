from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.shelf, name="shelf"),
    path("upload/", views.upload, name="upload"),
    path("book/<int:pk>/delete/", views.delete_book, name="delete_book"),
    path("book/<int:pk>/cover.jpg", views.cover, name="shelf_cover"),
    path("devices/", views.devices, name="devices"),
    path("devices/<int:pk>/reset/", views.device_reset, name="device_reset"),
    path("devices/<int:pk>/rename/", views.device_rename, name="device_rename"),
    path("devices/<int:pk>/revoke/", views.device_revoke, name="device_revoke"),
    path("help/", views.help_page, name="help"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="web/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
