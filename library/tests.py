import io
import zipfile

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings

from . import epub, storage
from .ingest import ingest
from .models import Book, Device, User
from .testutils import TempStorage, make_epub, upload_file


class IngestTests(TempStorage, TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reader", password="x")

    def test_accepts_a_real_epub_and_records_metadata(self):
        result = ingest(
            self.user,
            upload_file(title="Dune", author="Frank Herbert", series="Dune", seq=1),
        )
        self.assertTrue(result.ok, result.error)
        book = result.book
        self.assertEqual(book.title, "Dune")
        self.assertEqual(book.author, "Frank Herbert")
        self.assertEqual(book.series, "Dune")
        self.assertEqual(book.seq, 1.0)
        self.assertTrue(book.file_path.exists())
        self.assertEqual(book.size, book.file_path.stat().st_size)

    def test_cover_is_grayscale_jpeg_within_the_size_cap(self):
        from PIL import Image

        book = ingest(self.user, upload_file()).book
        self.assertTrue(book.has_cover)
        with Image.open(book.cover_path) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.mode, "L")
            self.assertLessEqual(max(image.size), settings.COVER_LONG_EDGE)

    def test_book_without_a_cover_is_still_accepted(self):
        book = ingest(self.user, upload_file(with_cover=False)).book
        self.assertFalse(book.has_cover)

    def test_extension_is_ignored_content_decides(self):
        payload = make_epub(title="Renamed")
        misnamed = SimpleUploadedFile("book.pdf", payload, "application/pdf")
        self.assertTrue(ingest(self.user, misnamed).ok)

        pdf = SimpleUploadedFile("real.epub", b"%PDF-1.7\nnot a zip", "application/epub+zip")
        result = ingest(self.user, pdf)
        self.assertFalse(result.ok)
        self.assertIn("PK", result.error)

    def test_zip_that_is_not_an_epub_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("hello.txt", "hi")
        result = ingest(
            self.user, SimpleUploadedFile("x.epub", buffer.getvalue(), "application/zip")
        )
        self.assertFalse(result.ok)
        self.assertIn("mimetype", result.error)

    def test_second_upload_by_same_owner_is_refused(self):
        payload = make_epub(title="Twice")
        first = ingest(self.user, SimpleUploadedFile("a.epub", payload))
        second = ingest(self.user, SimpleUploadedFile("b.epub", payload))
        self.assertTrue(first.ok)
        self.assertFalse(second.ok)
        self.assertEqual(second.error, "Already on your shelf.")
        self.assertEqual(Book.objects.count(), 1)

    def test_same_bytes_for_two_owners_are_stored_once(self):
        other = User.objects.create_user("other", password="x")
        payload = make_epub(title="Shared")
        mine = ingest(self.user, SimpleUploadedFile("a.epub", payload)).book
        theirs = ingest(other, SimpleUploadedFile("a.epub", payload)).book
        self.assertEqual(mine.sha256, theirs.sha256)
        self.assertEqual(Book.objects.count(), 2)
        self.assertEqual(
            len(list(settings.BOOKS_DIR.glob(f"{mine.sha256[:2]}/{mine.sha256}*"))), 1
        )

    @override_settings(MAX_UPLOAD_BYTES=2048)
    def test_oversize_upload_is_rejected_and_leaves_no_temp_file(self):
        result = ingest(self.user, upload_file(padding=20000))
        self.assertFalse(result.ok)
        self.assertIn("MB", result.error)
        self.assertEqual(list(settings.TMP_DIR.glob("*.part")), [])

    def test_failed_upload_leaves_no_temp_file(self):
        ingest(self.user, SimpleUploadedFile("x.epub", b"not a zip at all"))
        self.assertEqual(list(settings.TMP_DIR.glob("*.part")), [])

    def test_missing_title_falls_back_to_the_filename(self):
        payload = make_epub(title="")
        book = ingest(self.user, SimpleUploadedFile("The Fallback.epub", payload)).book
        self.assertEqual(book.title, "The Fallback")

    def test_deleting_the_last_owner_removes_the_blobs(self):
        other = User.objects.create_user("other", password="x")
        payload = make_epub(title="Shared")
        mine = ingest(self.user, SimpleUploadedFile("a.epub", payload)).book
        theirs = ingest(other, SimpleUploadedFile("a.epub", payload)).book
        path, cover = mine.file_path, mine.cover_path

        mine.delete_with_blobs()
        self.assertTrue(path.exists(), "another owner still holds these bytes")

        theirs.delete_with_blobs()
        self.assertFalse(path.exists())
        self.assertFalse(cover.exists())


class EpubParsingTests(TempStorage, TestCase):
    def test_epub3_collection_metadata(self):
        opf = """<?xml version="1.0"?>
        <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
          <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:title>Shards of Honour</dc:title>
            <dc:creator>Lois McMaster Bujold</dc:creator>
            <meta property="belongs-to-collection" id="c1">Vorkosigan Saga</meta>
            <meta refines="#c1" property="group-position">2.5</meta>
          </metadata>
          <manifest/>
        </package>"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED
            )
            zf.writestr("META-INF/container.xml", _container("book.opf"))
            zf.writestr("book.opf", opf)
        buffer.seek(0)
        with epub.open_epub(buffer) as zf:
            meta = epub.read_metadata(zf, epub.opf_path(zf))
        self.assertEqual(meta.title, "Shards of Honour")
        self.assertEqual(meta.series, "Vorkosigan Saga")
        self.assertEqual(meta.seq, 2.5)


class StorageTests(TestCase):
    def test_download_name_is_sanitised(self):
        self.assertEqual(
            storage.safe_download_name("../../etc/pa:ss wörd.epub", "T"),
            "pa_ss word.epub",
        )
        self.assertEqual(storage.safe_download_name("", "Fallback Title"), "Fallback Title.epub")


class DeviceTests(TestCase):
    def test_a_device_gets_a_unique_unambiguous_token(self):
        user = User.objects.create_user("reader", password="x")
        tokens = {Device.objects.create(user=user, name="X4").token for _ in range(5)}
        self.assertEqual(len(tokens), 5)
        for token in tokens:
            self.assertEqual(len(token), 16)
            # No l/1/0/O to squint at on a five-way keyboard.
            self.assertFalse(set(token) & set("ilo01"))

    def test_the_catalog_path_carries_the_token(self):
        user = User.objects.create_user("reader", password="x")
        device = Device.objects.create(user=user, name="Lounge X4")
        self.assertEqual(device.catalog_path, f"/k/{device.token}/")

    def test_rotating_kills_the_old_link(self):
        user = User.objects.create_user("reader", password="x")
        device = Device.objects.create(user=user, name="Lounge X4")
        old = device.token
        new = device.rotate_token()

        self.assertNotEqual(old, new)
        device.refresh_from_db()
        self.assertEqual(device.token, new)


class SweepTmpTests(TempStorage, TestCase):
    def test_only_old_fragments_are_swept(self):
        import os
        import time

        stale = settings.TMP_DIR / "stale.part"
        fresh = settings.TMP_DIR / "fresh.part"
        stale.write_bytes(b"x")
        fresh.write_bytes(b"x")
        old = time.time() - 48 * 3600
        os.utime(stale, (old, old))

        call_command("sweep_tmp", stdout=io.StringIO())
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())


class BackupTests(TempStorage, TransactionTestCase):
    def test_backup_writes_a_usable_snapshot_and_a_blob_tar(self):
        import sqlite3
        import tarfile

        user = User.objects.create_user("reader", password="x")
        ingest(user, upload_file(title="Backed up"))

        with self.settings(BACKUP_DIR=settings.DATA_DIR / "backup"):
            call_command("backup", stdout=io.StringIO())
            snapshots = sorted((settings.DATA_DIR / "backup").glob("library-*.db"))
            tars = sorted((settings.DATA_DIR / "backup").glob("books-*.tar"))

            self.assertEqual(len(snapshots), 1)
            connection = sqlite3.connect(snapshots[0])
            count = connection.execute("SELECT count(*) FROM library_book").fetchone()
            connection.close()
            self.assertEqual(count[0], 1)

            self.assertEqual(len(tars), 1)
            with tarfile.open(tars[0]) as tar:
                self.assertTrue(any(n.startswith("books/") for n in tar.getnames()))


def _container(opf_path):
    return f"""<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="{opf_path}" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
