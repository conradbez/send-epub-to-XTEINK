"""The upload pipeline: bytes in, one Book row and two blobs out."""

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction

from . import epub, storage
from .models import Book

logger = logging.getLogger(__name__)


class UploadRejected(Exception):
    pass


@dataclass
class IngestResult:
    filename: str
    book: Book | None = None
    created: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.book is not None


def _stream_to_temp(uploaded) -> tuple[Path, str, int]:
    """Write the upload to the volume, hashing as it goes. Never buffers whole."""
    temp_path = settings.TMP_DIR / f"{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    size = 0
    first = True
    try:
        with open(temp_path, "wb") as out:
            for chunk in uploaded.chunks():
                if first:
                    epub.check_magic(chunk[:4])
                    first = False
                size += len(chunk)
                if size > settings.MAX_UPLOAD_BYTES:
                    raise UploadRejected(
                        f"Larger than {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                    )
                digest.update(chunk)
                out.write(chunk)
    except Exception:
        storage.discard(temp_path)
        raise
    if size == 0:
        storage.discard(temp_path)
        raise UploadRejected("Empty file.")
    return temp_path, digest.hexdigest(), size


def ingest(user, uploaded) -> IngestResult:
    """Validate, parse, store. Any failure leaves nothing behind but a log line."""
    name = os.path.basename(getattr(uploaded, "name", "") or "book.epub")
    result = IngestResult(filename=name)

    try:
        temp_path, sha256, size = _stream_to_temp(uploaded)
    except (UploadRejected, epub.EpubError) as exc:
        result.error = str(exc)
        return result

    try:
        with epub.open_epub(temp_path) as zf:
            opf = epub.opf_path(zf)
            meta = epub.read_metadata(zf, opf)
            cover = epub.extract_cover(zf, opf, settings.COVER_LONG_EDGE)

        if Book.objects.filter(owner=user, sha256=sha256).exists():
            result.error = "Already on your shelf."
            return result

        title = meta.title or os.path.splitext(name)[0] or "Untitled"
        final_path = storage.book_path(sha256)
        if final_path.exists():
            # Someone else already uploaded these exact bytes; store once.
            storage.discard(temp_path)
        else:
            storage.place(temp_path, final_path)

        if cover:
            cover_path = storage.ensure_parent(storage.cover_path(sha256))
            if not cover_path.exists():
                tmp_cover = cover_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
                tmp_cover.write_bytes(cover)
                os.replace(tmp_cover, cover_path)

        try:
            with transaction.atomic():
                result.book = Book.objects.create(
                    owner=user,
                    sha256=sha256,
                    title=title[:500],
                    author=meta.author[:300],
                    series=meta.series[:300],
                    seq=meta.seq,
                    size=size,
                    filename=name[:500],
                    has_cover=bool(cover) or storage.cover_path(sha256).exists(),
                )
                result.created = True
        except IntegrityError:
            # Same file uploaded twice concurrently by the same user.
            result.book = Book.objects.filter(owner=user, sha256=sha256).first()
            result.error = "" if result.book else "Could not save."
        return result

    except epub.EpubError as exc:
        result.error = str(exc)
        return result
    except Exception:
        logger.exception("Upload failed for %s", name)
        result.error = "Could not read that file."
        return result
    finally:
        storage.discard(temp_path)
