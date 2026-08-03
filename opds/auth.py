"""HTTP Basic auth against Device credentials.

Device credentials are deliberately not the login password: a reader that is
lost or handed on gets revoked on its own, without disturbing the web login.
"""

import base64
import binascii
import datetime
from functools import wraps

from django.http import HttpResponse
from django.utils import timezone

from library.models import Device

REALM = "Library"
LAST_SEEN_INTERVAL = datetime.timedelta(minutes=5)


def _challenge() -> HttpResponse:
    response = HttpResponse("Authentication required.", status=401)
    response["WWW-Authenticate"] = f'Basic realm="{REALM}", charset="UTF-8"'
    return response


def _credentials(request) -> tuple[str, str] | None:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    scheme, _, payload = header.partition(" ")
    if scheme.lower() != "basic" or not payload:
        return None
    try:
        decoded = base64.b64decode(payload.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    username, sep, password = decoded.partition(":")
    return (username, password) if sep else None


def resolve_device(request) -> Device | None:
    credentials = _credentials(request)
    if not credentials:
        return None
    username, password = credentials
    device = Device.objects.select_related("user").filter(basic_user=username).first()
    if device is None or not device.check_device_password(password):
        return None
    return device


def _touch(device: Device) -> None:
    now = timezone.now()
    if device.last_seen is None or now - device.last_seen > LAST_SEEN_INTERVAL:
        Device.objects.filter(pk=device.pk).update(last_seen=now)
        device.last_seen = now


def basic_auth(view):
    """Attaches request.device and request.user, or challenges."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        device = resolve_device(request)
        if device is None:
            return _challenge()
        request.device = device
        request.user = device.user
        _touch(device)
        return view(request, *args, **kwargs)

    return wrapper
