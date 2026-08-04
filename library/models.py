import secrets

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import UniqueConstraint
from django.urls import reverse

from . import storage

# 31 unambiguous characters, 16 of them: ~79 bits. The paste route means this is
# rarely typed, but when it is, it is typed on a five-way keyboard.
TOKEN_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
TOKEN_LENGTH = 16


def make_token() -> str:
    """The whole credential: no username, no password field, one string.

    No uniqueness check: at ~79 bits a collision is not a thing that happens,
    and the column's unique constraint is there if it ever did. Django's system
    checks instantiate User(), so this must not touch the database.
    """
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))


class User(AbstractUser):
    """An account and its one reader — the same thing, addressed two ways.

    The web side is username + password; the reader side is the token, and the
    token is the whole credential. It is stored in the clear: /help/ shows the
    link whenever you ask, so a lost link is re-read rather than reset. It
    travels in the path, so it lands in access logs — the trade for a setup that
    never touches the on-device keyboard. Rotate it from /help/.
    """

    token = models.CharField(max_length=64, unique=True, default=make_token)
    last_seen = models.DateTimeField(null=True, blank=True)

    @property
    def catalog_path(self) -> str:
        return reverse("opds_root", args=[self.token])

    def rotate_token(self) -> str:
        """Old link dies immediately; the reader needs the new one pasted in."""
        self.token = make_token()
        self.save(update_fields=["token"])
        return self.token


class Book(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="books")
    sha256 = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=500)
    author = models.CharField(max_length=300, blank=True)
    series = models.CharField(max_length=300, blank=True)
    seq = models.FloatField(null=True, blank=True)
    size = models.BigIntegerField()
    filename = models.CharField(max_length=500)
    has_cover = models.BooleanField(default=False)
    added_at = models.DateTimeField(auto_now_add=True)
    # Null means it is still in the Inbox. One reader per account, so this is
    # the whole delivery record.
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-added_at"]
        constraints = [
            UniqueConstraint(fields=["owner", "sha256"], name="uniq_owner_sha")
        ]

    def __str__(self):
        return self.title

    @property
    def file_path(self):
        return storage.book_path(self.sha256)

    @property
    def cover_path(self):
        return storage.cover_path(self.sha256)

    @property
    def download_name(self) -> str:
        return storage.safe_download_name(self.filename, self.title)

    def delete_with_blobs(self) -> None:
        """Remove the row, and the files too if nobody else owns those bytes."""
        sha256 = self.sha256
        self.delete()
        if not Book.objects.filter(sha256=sha256).exists():
            storage.discard(storage.book_path(sha256))
            storage.discard(storage.cover_path(sha256))

    @property
    def byline(self) -> str:
        bits = [self.author] if self.author else []
        if self.series:
            bits.append(
                f"{self.series} #{self.seq:g}" if self.seq is not None else self.series
            )
        return " — ".join(bits)
