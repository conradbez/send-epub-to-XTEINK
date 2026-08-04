from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.shelf, name="shelf"),
    path("upload/", views.upload, name="upload"),
    path("book/<int:pk>/delete/", views.delete_book, name="delete_book"),
    path("book/<int:pk>/cover.jpg", views.cover, name="shelf_cover"),
    path("help/", views.help_page, name="help"),
    path("help/new-link/", views.reset_link, name="reset_link"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="web/login.html"),
        name="login",
    ),
    path("signup/", views.signup, name="signup"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
