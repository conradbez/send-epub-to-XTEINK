"""Builds real EPUB bytes for tests — the pipeline only trusts real bytes."""

import io
import zipfile

from PIL import Image

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""


def _opf(title, author, series, seq, with_cover):
    series_meta = ""
    if series:
        series_meta = f'<meta name="calibre:series" content="{series}"/>'
        if seq is not None:
            series_meta += f'<meta name="calibre:series_index" content="{seq}"/>'
    cover_meta = '<meta name="cover" content="cover-image"/>' if with_cover else ""
    cover_item = (
        '<item id="cover-image" href="images/cover.png" media-type="image/png"/>'
        if with_cover
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:identifier id="bookid">urn:test:{title}</dc:identifier>
    {series_meta}
    {cover_meta}
  </metadata>
  <manifest>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
    {cover_item}
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>"""


def make_epub(
    title="A Test Book",
    author="Ann Author",
    series="",
    seq=None,
    with_cover=True,
    padding=0,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED
        )
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", _opf(title, author, series, seq, with_cover))
        zf.writestr(
            "OEBPS/chapter.xhtml",
            f"<html><body><h1>{title}</h1><p>{'x' * padding}</p></body></html>",
        )
        if with_cover:
            image = Image.new("RGB", (600, 900), (120, 60, 30))
            out = io.BytesIO()
            image.save(out, format="PNG")
            zf.writestr("OEBPS/images/cover.png", out.getvalue())
    return buffer.getvalue()


def upload_file(name="book.epub", **kwargs):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, make_epub(**kwargs), "application/epub+zip")
