"""Content-addressed blobs, stored inside the SQLite file itself.

Books and covers are rows in ``library_blob`` keyed by the content hash, so the
database file *is* the library: one file to back up, one file to restore, and no
way for the rows and the bytes to drift apart on a volume nobody snapshots.

Nothing here is ever held whole. Uploads stream from their temp file into a
``zeroblob`` and downloads stream back out again, both through SQLite's
incremental blob I/O, so a 50 MB book costs 64 KB of memory in either direction.

The table is named rather than imported: ``library.models`` imports this module,
so importing the model back would close the loop.
"""

import os
import re
import unicodedata

from django.db import connection, transaction

TABLE = "library_blob"
CHUNK = 64 * 1024


def _rowid(cursor, sha256: str) -> int | None:
    """SQLite's incremental blob API addresses rows by rowid, not by key."""
    cursor.execute(f"SELECT rowid FROM {TABLE} WHERE sha256 = %s", [sha256])
    row = cursor.fetchone()
    return row[0] if row else None


def exists(sha256: str) -> bool:
    return size(sha256) is not None


def size(sha256: str) -> int | None:
    """Stored length, or None if these bytes are not here — the 404 check."""
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT size FROM {TABLE} WHERE sha256 = %s", [sha256])
        row = cursor.fetchone()
    return row[0] if row else None


def has_cover(sha256: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT cover IS NOT NULL FROM {TABLE} WHERE sha256 = %s", [sha256]
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def store(sha256: str, source_path, byte_count: int, cover: bytes | None = None) -> None:
    """Move a finished temp file into the database, without reading it whole.

    Content-addressed, so two accounts uploading the same book store it once —
    and a second upload that happens to carry a cover fills in one the first was
    missing. Insert and fill happen in one transaction: a crash mid-write leaves
    no half-written book behind, only no book at all.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT rowid, cover IS NOT NULL FROM {TABLE} WHERE sha256 = %s",
                [sha256],
            )
            row = cursor.fetchone()
            if row is not None:
                if cover and not row[1]:
                    cursor.execute(
                        f"UPDATE {TABLE} SET cover = %s WHERE sha256 = %s",
                        [cover, sha256],
                    )
                return

            cursor.execute(
                f"INSERT INTO {TABLE} (sha256, size, data, cover) "
                f"VALUES (%s, %s, zeroblob(%s), %s)",
                [sha256, byte_count, byte_count, cover],
            )
            rowid = _rowid(cursor, sha256)

        with connection.connection.blobopen(TABLE, "data", rowid) as blob:
            with open(source_path, "rb") as source:
                while chunk := source.read(CHUNK):
                    blob.write(chunk)


def stream(sha256: str, chunk_size: int = CHUNK):
    """Yield the book a chunk at a time, straight out of the blob."""
    with connection.cursor() as cursor:
        rowid = _rowid(cursor, sha256)
    if rowid is None:
        return

    blob = connection.connection.blobopen(TABLE, "data", rowid, readonly=True)
    try:
        while data := blob.read(chunk_size):
            yield data
    finally:
        blob.close()


def read_cover(sha256: str) -> bytes | None:
    """Covers are a few KB of grayscale JPEG; those do come back whole."""
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT cover FROM {TABLE} WHERE sha256 = %s", [sha256])
        row = cursor.fetchone()
    return bytes(row[0]) if row and row[0] is not None else None


def drop(sha256: str) -> None:
    """Forget these bytes. The caller has established nobody still owns them."""
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {TABLE} WHERE sha256 = %s", [sha256])


def total_bytes() -> int:
    """Everything stored, counting shared bytes once."""
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COALESCE(SUM(size), 0) FROM {TABLE}")
        return cursor.fetchone()[0]


def discard(path) -> None:
    """Remove a temp file. Uploads still land on disk before they land here."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def safe_download_name(filename: str, fallback_title: str) -> str:
    """A filename the reader will accept: ASCII-ish, no separators, .epub."""
    name = os.path.basename(filename or "")
    stem = os.path.splitext(name)[0] or fallback_title or "book"
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem).strip(" .") or "book"
    return f"{stem[:120]}.epub"
