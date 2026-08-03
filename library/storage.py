"""Content-addressed paths on the volume.

Blobs live beside the database on the same filesystem, so an upload finishes
with an atomic rename and no partial file is ever visible.
"""

import os
import re
import unicodedata
from pathlib import Path

from django.conf import settings


def _fanned(root: Path, sha256: str, suffix: str) -> Path:
    return root / sha256[:2] / f"{sha256}{suffix}"


def book_path(sha256: str) -> Path:
    return _fanned(settings.BOOKS_DIR, sha256, ".epub")


def cover_path(sha256: str) -> Path:
    return _fanned(settings.COVERS_DIR, sha256, ".jpg")


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def place(temp_path: Path, final_path: Path) -> None:
    """Atomically move a finished temp file into its content-addressed home."""
    ensure_parent(final_path)
    os.replace(temp_path, final_path)


def discard(path) -> None:
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


def dir_size(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for f in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total
