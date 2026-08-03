"""Capability-URL auth: the token in the path *is* the credential.

Typing a URL plus a username plus a password on a five-way keyboard was the
worst step in the whole flow. One string replaces all three. Still per device,
still revocable on its own without disturbing the web login — a reader that is
lost or handed on gets its link rotated and nothing else changes.
"""

import datetime
from functools import wraps

from django.http import Http404
from django.utils import timezone

from library.models import Device

LAST_SEEN_INTERVAL = datetime.timedelta(minutes=5)


def resolve_device(token: str) -> Device | None:
    return Device.objects.select_related("user").filter(token=token).first()


def _touch(device: Device) -> None:
    now = timezone.now()
    if device.last_seen is None or now - device.last_seen > LAST_SEEN_INTERVAL:
        Device.objects.filter(pk=device.pk).update(last_seen=now)
        device.last_seen = now


def device_token(view):
    """Swaps the URL's token for request.device and request.user, or 404s.

    A 404 and not a 401: there is no realm to challenge for, and a wrong token
    should look exactly like a URL that was never a catalog.
    """

    @wraps(view)
    def wrapper(request, token, *args, **kwargs):
        device = resolve_device(token)
        if device is None:
            raise Http404
        request.device = device
        request.user = device.user
        _touch(device)
        return view(request, *args, **kwargs)

    return wrapper
