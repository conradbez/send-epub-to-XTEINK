import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import UniqueConstraint

from . import storage


class User(AbstractUser):
    pass


def _make_basic_user(name: str) -> str:
    """A short, typeable username for a device. Unique across all devices."""
    stem = "".join(c for c in name.lower() if c.isalnum())[:12] or "device"
    for _ in range(20):
        candidate = f"{stem}-{secrets.token_hex(2)}"
        if not Device.objects.filter(basic_user=candidate).exists():
            return candidate
    return f"{stem}-{secrets.token_hex(6)}"


def make_device_password() -> str:
    """Typed once, on a device with no keyboard. Unambiguous characters only."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


class Device(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    name = models.CharField(max_length=100)
    basic_user = models.CharField(max_length=64, unique=True)
    pw_hash = models.CharField(max_length=256)
    last_seen = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.basic_user})"

    def set_password(self, raw: str) -> None:
        self.pw_hash = make_password(raw)

    def check_device_password(self, raw: str) -> bool:
        return check_password(raw, self.pw_hash)

    @classmethod
    def create_with_credentials(cls, user, name: str) -> tuple["Device", str]:
        """Returns the device and its plaintext password, shown once."""
        raw = make_device_password()
        device = cls(user=user, name=name, basic_user=_make_basic_user(name))
        device.set_password(raw)
        device.save()
        return device, raw

    def reset_password(self) -> str:
        raw = make_device_password()
        self.set_password(raw)
        self.save(update_fields=["pw_hash"])
        return raw


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
