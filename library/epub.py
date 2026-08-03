"""EPUB validation, metadata and cover extraction.

Nothing here trusts the filename: a file is an EPUB because its bytes say so.
Reads out of the archive are capped so a malicious zip cannot balloon memory.
"""

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from urllib.parse import unquote

from PIL import Image

DC_NS = "http://purl.org/dc/elements/1.1/"
OPF_NS = "http://www.idpf.org/2007/opf"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

ZIP_MAGIC = b"PK\x03\x04"
MAX_XML_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 16 * 1024 * 1024


class EpubError(Exception):
    """The file is not an EPUB we will accept."""


@dataclass
class EpubMetadata:
    title: str = ""
    author: str = ""
    series: str = ""
    seq: float | None = None


def _fromstring(data: bytes):
    # Imported lazily so the module stays cheap to import; stdlib ElementTree
    # does not expand external entities, which is the property we rely on.
    from xml.etree import ElementTree

    return ElementTree.fromstring(data)


def _read(zf: zipfile.ZipFile, name: str, limit: int) -> bytes:
    info = zf.getinfo(name)
    if info.file_size > limit:
        raise EpubError(f"{name} is implausibly large")
    with zf.open(info) as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise EpubError(f"{name} is implausibly large")
    return data


def check_magic(head: bytes) -> None:
    """First bytes of the upload, before we have a complete file."""
    if not head.startswith(ZIP_MAGIC):
        raise EpubError("Not a zip archive — EPUB files start with PK.")


def open_epub(source) -> zipfile.ZipFile:
    """Open and structurally validate a path or file object.

    The caller closes the returned handle.
    """
    if hasattr(source, "read"):
        source.seek(0)
        check_magic(source.read(4))
        source.seek(0)
    else:
        with open(source, "rb") as fh:
            check_magic(fh.read(4))

    try:
        zf = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise EpubError("Damaged zip archive.") from exc

    entries = zf.infolist()
    if not entries:
        raise EpubError("Empty archive.")

    first = entries[0]
    if first.filename != "mimetype":
        raise EpubError("First archive entry must be 'mimetype'.")
    if first.compress_type != zipfile.ZIP_STORED:
        raise EpubError("The 'mimetype' entry must be stored uncompressed.")
    if first.file_size > 64:
        raise EpubError("The 'mimetype' entry is not a media type.")
    if zf.read(first).strip() != b"application/epub+zip":
        raise EpubError("Media type is not application/epub+zip.")

    if "META-INF/container.xml" not in zf.namelist():
        raise EpubError("Missing META-INF/container.xml.")
    return zf


def opf_path(zf: zipfile.ZipFile) -> str:
    root = _fromstring(_read(zf, "META-INF/container.xml", MAX_XML_BYTES))
    for rootfile in root.iter(f"{{{CONTAINER_NS}}}rootfile"):
        full_path = rootfile.get("full-path")
        if full_path:
            return full_path.lstrip("/")
    # Some builders omit the namespace; fall back to a tag-name match.
    for rootfile in root.iter():
        if rootfile.tag.rsplit("}", 1)[-1] == "rootfile" and rootfile.get("full-path"):
            return rootfile.get("full-path").lstrip("/")
    raise EpubError("container.xml names no OPF file.")


def _text(element) -> str:
    return " ".join((element.text or "").split()) if element is not None else ""


def _parse_seq(raw: str | None) -> float | None:
    if not raw:
        return None
    match = re.search(r"\d+(?:\.\d+)?", raw)
    return float(match.group()) if match else None


def read_metadata(zf: zipfile.ZipFile, opf: str) -> EpubMetadata:
    root = _fromstring(_read(zf, opf, MAX_XML_BYTES))
    meta = EpubMetadata()

    titles = root.iter(f"{{{DC_NS}}}title")
    meta.title = next((t for t in (_text(e) for e in titles) if t), "")

    creators = [_text(e) for e in root.iter(f"{{{DC_NS}}}creator")]
    meta.author = ", ".join([c for c in creators if c][:3])

    collection_ids = {}
    for element in root.iter(f"{{{OPF_NS}}}meta"):
        name, content = element.get("name"), element.get("content")
        if name == "calibre:series" and content:
            meta.series = content.strip()
        elif name == "calibre:series_index" and not meta.seq:
            meta.seq = _parse_seq(content)
        # EPUB 3 spelling of the same idea.
        elif element.get("property") == "belongs-to-collection":
            if not meta.series:
                meta.series = _text(element)
            if element.get("id"):
                collection_ids[f"#{element.get('id')}"] = True
        elif element.get("property") == "group-position" and meta.seq is None:
            if element.get("refines") in collection_ids or not collection_ids:
                meta.seq = _parse_seq(element.text)

    return meta


def _manifest(root):
    for item in root.iter(f"{{{OPF_NS}}}item"):
        yield item


def find_cover_href(zf: zipfile.ZipFile, opf: str) -> str | None:
    """OPF <meta name="cover">, then properties="cover-image", then any image."""
    root = _fromstring(_read(zf, opf, MAX_XML_BYTES))

    cover_id = None
    for element in root.iter(f"{{{OPF_NS}}}meta"):
        if element.get("name") == "cover" and element.get("content"):
            cover_id = element.get("content")
            break

    by_id, by_property, first_image = None, None, None
    for item in _manifest(root):
        href, media = item.get("href"), (item.get("media-type") or "")
        if not href or not media.startswith("image/"):
            continue
        if cover_id and item.get("id") == cover_id:
            by_id = href
        if "cover-image" in (item.get("properties") or ""):
            by_property = by_property or href
        first_image = first_image or href

    href = by_id or by_property or first_image
    if not href:
        return None

    base = posixpath.dirname(opf)
    resolved = posixpath.normpath(posixpath.join(base, unquote(href))).lstrip("/")
    names = set(zf.namelist())
    return resolved if resolved in names else (href if href in names else None)


def render_cover(zf: zipfile.ZipFile, href: str, long_edge: int) -> bytes | None:
    """Grayscale JPEG, long edge capped. The readers discard colour anyway and
    this roughly halves the bytes for the asset fetched most often."""
    try:
        raw = _read(zf, href, MAX_IMAGE_BYTES)
    except (KeyError, EpubError):
        return None

    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.draft("L", (long_edge, long_edge))
            image = image.convert("L")
            image.thumbnail((long_edge, long_edge), Image.LANCZOS)
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=80, optimize=True)
            return out.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def extract_cover(zf: zipfile.ZipFile, opf: str, long_edge: int) -> bytes | None:
    href = find_cover_href(zf, opf)
    return render_cover(zf, href, long_edge) if href else None
