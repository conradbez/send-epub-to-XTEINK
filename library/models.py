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


class User(AbstractUser):
    pass


def make_device_token() -> str:
    """The whole credential: no username, no password field, one string."""
    for _ in range(20):
        candidate = "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))
        if not Device.objects.filter(token=candidate).exists():
            return candidate
    raise RuntimeError("Could not mint a unique device token")


class Device(models.Model):
    """A reader, authenticated by a capability URL rather than a password.

    The token is the credential and it is stored in the clear: /help/ shows each
    reader's link whenever you ask, so a lost link is re-read rather than reset.
    It travels in the path, so it lands in access logs — the trade for a setup
    that never touches the on-device keyboard. Rotate from /devices/.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    name = models.CharField(max_length=100)
    token = models.CharField(max_length=64, unique=True, default=make_device_token)
    last_seen = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def catalog_path(self) -> str:
        return reverse("opds_root", args=[self.token])

    def rotate_token(self) -> str:
        """Old link dies immediately; the reader needs the new one pasted in."""
        self.token = make_device_token()
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


class Delivery(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="deliveries")
    device = models.ForeignKey(
        Device, on_delete=models.CASCADE, related_name="deliveries"
    )
    downloaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["book", "device"], name="uniq_book_device")
        ]

    def __str__(self):
        return f"{self.book_id} → {self.device_id}"
