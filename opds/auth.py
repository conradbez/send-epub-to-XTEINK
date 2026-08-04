"""Capability-URL auth: the token in the path *is* the credential.

Typing a URL plus a username plus a password on a five-way keyboard was the
worst step in the whole flow. One string replaces all three, and it is revocable
on its own without disturbing the web login — a reader that is lost or handed on
gets its link rotated and the account is otherwise untouched.
"""

import datetime
from functools import wraps

from django.http import Http404
from django.utils import timezone

from library.models import User

LAST_SEEN_INTERVAL = datetime.timedelta(minutes=5)


def resolve_user(token: str) -> User | None:
    return User.objects.filter(token=token).first()


def _touch(user: User) -> None:
    now = timezone.now()
    if user.last_seen is None or now - user.last_seen > LAST_SEEN_INTERVAL:
        User.objects.filter(pk=user.pk).update(last_seen=now)
        user.last_seen = now


def catalog_token(view):
    """Swaps the URL's token for request.user, or 404s.

    A 404 and not a 401: there is no realm to challenge for, and a wrong token
    should look exactly like a URL that was never a catalog.
    """

    @wraps(view)
    def wrapper(request, token, *args, **kwargs):
        user = resolve_user(token)
        if user is None:
            raise Http404
        request.user = user
        _touch(user)
        return view(request, *args, **kwargs)

    return wrapper
