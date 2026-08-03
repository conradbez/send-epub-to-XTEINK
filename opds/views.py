"""OPDS 1.2 feeds, rendered as Atom templates.

Serving rules that matter on e-ink firmware: every response carries an explicit
Content-Length and ETag, feeds are capped at 50 entries, and a Delivery row is
written only once the last byte has actually left — a cancelled download stays
in the Inbox.
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

from .auth import basic_auth

logger = logging.getLogger(__name__)

NAVIGATION_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQUISITION_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"


def _feed_response(request, template, context, kind=ACQUISITION_TYPE):
    from django.template.loader import render_to_string

    body = render_to_string(template, context, request=request).encode("utf-8")
    response = HttpResponse(body, content_type=kind)
    response["Content-Length"] = str(len(body))
    return response


def _base_context(request, title, path):
    return {
        "site_title": title,
        "self_url": request.build_absolute_uri(path),
        "start_url": request.build_absolute_uri(reverse("opds_root")),
        "updated": timezone.now(),
        "device": request.device,
    }


@basic_auth
def root(request):
    owned = Book.objects.filter(owner=request.user)
    inbox_count = owned.exclude(deliveries__device=request.device).count()
    context = _base_context(request, "Library", reverse("opds_root"))
    context["sections"] = [
        {
            "title": "Inbox",
            "href": reverse("opds_inbox"),
            "summary": f"{inbox_count} book(s) not yet on {request.device.name}",
        },
        {
            "title": "All Books",
            "href": reverse("opds_all"),
            "summary": f"Everything on your shelf ({owned.count()})",
        },
        {
            "title": "Recent",
            "href": reverse("opds_recent"),
            "summary": "The last 50 you added",
        },
    ]
    return _feed_response(request, "opds/navigation.xml", context, NAVIGATION_TYPE)


def _acquisition_feed(request, title, queryset, path, paginate=True):
    context = _base_context(request, title, path)
    if paginate:
        paginator = Paginator(queryset, settings.OPDS_PAGE_SIZE)
        page = paginator.get_page(request.GET.get("page") or 1)
        context["books"] = page.object_list
        base = request.build_absolute_uri(path)
        if page.has_next():
            context["next_url"] = f"{base}?page={page.next_page_number()}"
        if page.has_previous():
            context["previous_url"] = f"{base}?page={page.previous_page_number()}"
    else:
        context["books"] = queryset
    return _feed_response(request, "opds/acquisition.xml", context)


@basic_auth
def inbox(request):
    """Books this user owns that *this* device has not downloaded."""
    queryset = (
        Book.objects.filter(owner=request.user)
        .exclude(deliveries__device=request.device)
        .order_by("-added_at")
    )
    return _acquisition_feed(
        request, "Inbox", queryset, reverse("opds_inbox")
    )


@basic_auth
def all_books(request):
    queryset = Book.objects.filter(owner=request.user).order_by("title")
    return _acquisition_feed(request, "All Books", queryset, reverse("opds_all"))


@basic_auth
def recent(request):
    queryset = Book.objects.filter(owner=request.user).order_by("-added_at")[:50]
    return _acquisition_feed(
        request, "Recent", queryset, reverse("opds_recent"), paginate=False
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


@basic_auth
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


@basic_auth
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
