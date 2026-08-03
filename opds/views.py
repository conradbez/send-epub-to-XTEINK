"""OPDS 1.2 feeds, rendered as Atom templates.

Serving rules that matter on e-ink firmware: every response carries an explicit
Content-Length and ETag, feeds are capped at 50 entries, and a Delivery row is
written only once the last byte has actually left — a cancelled download stays
in the Inbox.

Every URL carries the device's token, so a feed can only ever link to feeds for
the same device. There is no shared entry point to get lost in.
"""

import logging

from django.conf import settings
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from library.models import Book, Delivery

from .auth import device_token

logger = logging.getLogger(__name__)

ACQUISITION_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"


def _url(request, name, *args) -> str:
    return reverse(name, args=[request.device.token, *args])


def _feed_response(request, context):
    from django.template.loader import render_to_string

    body = render_to_string("opds/acquisition.xml", context, request=request)
    body = body.encode("utf-8")
    response = HttpResponse(body, content_type=ACQUISITION_TYPE)
    response["Content-Length"] = str(len(body))
    return response


def _acquisition_feed(request, title, queryset, path, paginate=True, sections=()):
    context = {
        "site_title": title,
        "self_url": request.build_absolute_uri(path),
        "start_url": request.build_absolute_uri(_url(request, "opds_root")),
        "updated": timezone.now(),
        "device": request.device,
        "token": request.device.token,
        "sections": sections,
    }
    if paginate:
        paginator = Paginator(queryset, settings.OPDS_PAGE_SIZE)
        page = paginator.get_page(request.GET.get("page") or 1)
        context["books"] = page.object_list
        base = request.build_absolute_uri(path)
        if page.has_next():
            context["next_url"] = f"{base}?page={page.next_page_number()}"
        if page.has_previous():
            context["previous_url"] = f"{base}?page={page.previous_page_number()}"
        # Sub-feeds belong after the books, and only where the list ends —
        # repeating them on every page just pushes books further down.
        if page.has_next():
            context["sections"] = ()
    else:
        context["books"] = queryset
    return _feed_response(request, context)


@device_token
def inbox(request):
    """The root feed: books this user owns that *this* device has not taken.

    All Books and Recent hang off the end of it as sub-feeds, so the catalog
    opens on the new books and navigation is something you opt into.
    """
    owned = Book.objects.filter(owner=request.user)
    queryset = owned.exclude(deliveries__device=request.device).order_by("-added_at")
    sections = [
        {
            "title": "All Books",
            "href": _url(request, "opds_all"),
            "summary": f"Everything on your shelf ({owned.count()})",
        },
        {
            "title": "Recent",
            "href": _url(request, "opds_recent"),
            "summary": "The last 50 you added, delivered or not",
        },
    ]
    return _acquisition_feed(
        request, "Inbox", queryset, _url(request, "opds_root"), sections=sections
    )


@device_token
def all_books(request):
    queryset = Book.objects.filter(owner=request.user).order_by("title")
    return _acquisition_feed(
        request, "All Books", queryset, _url(request, "opds_all")
    )


@device_token
def recent(request):
    queryset = Book.objects.filter(owner=request.user).order_by("-added_at")[:50]
    return _acquisition_feed(
        request, "Recent", queryset, _url(request, "opds_recent"), paginate=False
    )


def _record_delivery(book_id: int, device_id: int) -> None:
    try:
        Delivery.objects.get_or_create(book_id=book_id, device_id=device_id)
    except IntegrityError:
        pass
    except Exception:
        logger.exception("Could not record delivery %s → %s", book_id, device_id)


def _tracked(chunks, expected: int, book_id: int, device_id: int):
    """Yield the file, then record the delivery — only if it all got out."""
    sent = 0
    for chunk in chunks:
        sent += len(chunk)
        yield chunk
    if sent >= expected:
        _record_delivery(book_id, device_id)


@device_token
def acquire(request, pk):
    book = get_object_or_404(Book, pk=pk, owner=request.user)
    path = book.file_path
    if not path.exists():
        logger.error("Book %s missing from volume: %s", book.pk, path)
        raise Http404

    etag = f'"{book.sha256}"'
    if request.headers.get("If-None-Match") == etag:
        # The device already holds these bytes; nothing was delivered now.
        response = HttpResponse(status=304)
        response["ETag"] = etag
        return response

    size = path.stat().st_size
    response = FileResponse(
        open(path, "rb"),
        content_type="application/epub+zip",
        as_attachment=True,
        filename=book.download_name,
    )
    response.streaming_content = _tracked(
        response.streaming_content, size, book.pk, request.device.pk
    )
    # Set after wrapping the body: explicit length, never chunked encoding —
    # constrained clients handle a known length far more predictably.
    response["Content-Length"] = str(size)
    response["ETag"] = etag
    response["Cache-Control"] = "private, max-age=0"
    return response


@device_token
def cover(request, pk):
    book = get_object_or_404(Book, pk=pk, owner=request.user)
    path = book.cover_path
    if not book.has_cover or not path.exists():
        raise Http404

    etag = f'"{book.sha256}-cover"'
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponse(status=304)
        response["ETag"] = etag
        return response

    response = FileResponse(open(path, "rb"), content_type="image/jpeg")
    response["Content-Length"] = str(path.stat().st_size)
    response["ETag"] = etag
    response["Cache-Control"] = "private, max-age=604800"
    return response
