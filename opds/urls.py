from django.urls import path

from . import views

urlpatterns = [
    path("", views.root, name="opds_root"),
    path("inbox/", views.inbox, name="opds_inbox"),
    path("all/", views.all_books, name="opds_all"),
    path("recent/", views.recent, name="opds_recent"),
    path("book/<int:pk>.epub", views.acquire, name="opds_acquire"),
    path("cover/<int:pk>.jpg", views.cover, name="opds_cover"),
]
