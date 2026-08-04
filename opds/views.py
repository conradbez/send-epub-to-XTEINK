"""OPDS 1.2 feeds, rendered as Atom templates.

Serving rules that matter on e-ink firmware: every response carries an explicit
Content-Length and ETag, feeds are capped at 50 entries, and a book is marked
delivered only once the last byte has actually left — a cancelled download stays
in the Inbox.

Every URL carries the account's token, so a feed can only ever link to feeds for
the same shelf. There is no shared entry point to get lost in.
"""

import logging

from django.conf import settings
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from library import storage
from library.models import Book

from .auth import catalog_token

logger = logging.getLogger(__name__)

ACQUISITION_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"


def _url(request, name, *args) -> str:
    return reverse(name, args=[request.user.token, *args])


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
        "token": request.user.token,
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


@catalog_token
def inbox(request):
    """The root feed: books on this shelf the reader has not taken yet.

    All Books and Recent hang off the end of it as sub-feeds, so the catalog
    opens on the new books and navigation is something you opt into.
    """
    owned = Book.objects.filter(owner=request.user)
    queryset = owned.filter(delivered_at__isnull=True).order_by("-added_at")
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


@catalog_token
def all_books(request):
    queryset = Book.objects.filter(owner=request.user).order_by("title")
    return _acquisition_feed(
        request, "All Books", queryset, _url(request, "opds_all")
    )


@catalog_token
def recent(request):
    queryset = Book.objects.filter(owner=request.user).order_by("-added_at")[:50]
    return _acquisition_feed(
        request, "Recent", queryset, _url(request, "opds_recent"), paginate=False
    )


def _record_delivery(book_id: int) -> None:
    try:
        # Only the first delivery stamps a time; downloading again is a no-op.
        Book.objects.filter(pk=book_id, delivered_at__isnull=True).update(
            delivered_at=timezone.now()
        )
    except Exception:
        logger.exception("Could not record delivery of %s", book_id)


def _tracked(chunks, expected: int, book_id: int):
    """Yield the file, then record the delivery — only if it all got out."""
    sent = 0
    for chunk in chunks:
        sent += len(chunk)
        yield chunk
    if sent >= expected:
        _record_delivery(book_id)


@catalog_token
def acquire(request, pk):
    book = get_object_or_404(Book, pk=pk, owner=request.user)
    size = storage.size(book.sha256)
    if size is None:
        logger.error("Book %s has no stored bytes: %s", book.pk, book.sha256)
        raise Http404

    etag = f'"{book.sha256}"'
    if request.headers.get("If-None-Match") == etag:
        # The device already holds these bytes; nothing was delivered now.
        response = HttpResponse(status=304)
        response["ETag"] = etag
        return response

    response = StreamingHttpResponse(
        _tracked(storage.stream(book.sha256), size, book.pk),
        content_type="application/epub+zip",
    )
    # download_name is ASCII by construction, so the plain form is enough.
    response["Content-Disposition"] = f'attachment; filename="{book.download_name}"'
    # Explicit length, never chunked encoding — constrained clients handle a
    # known length far more predictably.
    response["Content-Length"] = str(size)
    response["ETag"] = etag
    response["Cache-Control"] = "private, max-age=0"
    return response


@catalog_token
def cover(request, pk):
    book = get_object_or_404(Book, pk=pk, owner=request.user)
    if not book.has_cover:
        raise Http404

    etag = f'"{book.sha256}-cover"'
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponse(status=304)
        response["ETag"] = etag
        return response

    data = storage.read_cover(book.sha256)
    if data is None:
        raise Http404

    response = HttpResponse(data, content_type="image/jpeg")
    response["Content-Length"] = str(len(data))
    response["ETag"] = etag
    response["Cache-Control"] = "private, max-age=604800"
    return response
