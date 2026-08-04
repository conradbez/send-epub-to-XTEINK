from django.urls import path, register_converter

from library.models import TOKEN_ALPHABET

from . import views


class TokenConverter:
    """Only ever matches strings shaped like a catalog token."""

    regex = f"[{TOKEN_ALPHABET}]{{8,64}}"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


register_converter(TokenConverter, "token")

urlpatterns = [
    # The root *is* the Inbox. There is no on-device search, so every tap saved
    # matters: opening the catalog shows exactly the new books, zero navigation.
    path("<token:token>/", views.inbox, name="opds_root"),
    path("<token:token>/all/", views.all_books, name="opds_all"),
    path("<token:token>/recent/", views.recent, name="opds_recent"),
    path("<token:token>/book/<int:pk>.epub", views.acquire, name="opds_acquire"),
    path("<token:token>/cover/<int:pk>.jpg", views.cover, name="opds_cover"),
]
