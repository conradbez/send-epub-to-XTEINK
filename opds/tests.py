import base64
from xml.etree import ElementTree

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from library.ingest import ingest
from library.models import Book, Delivery, Device, User
from library.testutils import TempStorage, make_epub

from .views import _tracked

ATOM = "{http://www.w3.org/2005/Atom}"


def basic(username, password):
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"authorization": f"Basic {token}"}


class OpdsTestCase(TempStorage, TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reader", password="x")
        self.device, self.password = Device.create_with_credentials(
            self.user, "Lounge X4"
        )
        self.auth = basic(self.device.basic_user, self.password)

    def add_book(self, title="A Book", owner=None):
        payload = make_epub(title=title)
        return ingest(owner or self.user, SimpleUploadedFile("b.epub", payload)).book

    def feed(self, url, **kwargs):
        response = self.client.get(url, headers=self.auth, **kwargs)
        self.assertEqual(response.status_code, 200)
        return ElementTree.fromstring(response.content), response

    def titles(self, root):
        return [
            entry.find(f"{ATOM}title").text for entry in root.findall(f"{ATOM}entry")
        ]


class AuthTests(OpdsTestCase):
    def test_no_credentials_gets_a_basic_challenge(self):
        response = self.client.get("/opds/")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response["WWW-Authenticate"])

    def test_wrong_password_is_refused(self):
        response = self.client.get(
            "/opds/", headers=basic(self.device.basic_user, "nope")
        )
        self.assertEqual(response.status_code, 401)

    def test_malformed_header_is_refused(self):
        for header in ({"authorization": "Basic !!!"}, {"authorization": "Bearer x"}):
            self.assertEqual(self.client.get("/opds/", headers=header).status_code, 401)

    def test_revoked_device_loses_access(self):
        self.device.delete()
        self.assertEqual(self.client.get("/opds/", headers=self.auth).status_code, 401)

    def test_successful_request_records_last_seen(self):
        self.client.get("/opds/", headers=self.auth)
        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.last_seen)


class FeedTests(OpdsTestCase):
    def test_root_is_a_navigation_feed_with_three_sections(self):
        root, response = self.feed("/opds/")
        self.assertIn("kind=navigation", response["Content-Type"])
        self.assertEqual(self.titles(root), ["Inbox", "All Books", "Recent"])
        self.assertTrue(response["Content-Length"])

    def test_feeds_are_well_formed_and_scoped_to_the_owner(self):
        self.add_book("Mine")
        stranger = User.objects.create_user("stranger", password="x")
        self.add_book("Theirs", owner=stranger)

        root, response = self.feed("/opds/all/")
        self.assertIn("kind=acquisition", response["Content-Type"])
        self.assertEqual(self.titles(root), ["Mine"])

    def test_entry_carries_acquisition_and_thumbnail_links(self):
        book = self.add_book("Linked")
        root, _ = self.feed("/opds/all/")
        links = {
            link.get("rel"): link for link in root.iter(f"{ATOM}link")
        }
        acquisition = links["http://opds-spec.org/acquisition"]
        self.assertEqual(acquisition.get("type"), "application/epub+zip")
        self.assertEqual(acquisition.get("href"), f"/opds/book/{book.pk}.epub")
        self.assertEqual(acquisition.get("length"), str(book.size))
        thumbnail = links["http://opds-spec.org/image/thumbnail"]
        self.assertEqual(thumbnail.get("href"), f"/opds/cover/{book.pk}.jpg")

    def test_acquisition_feeds_page_at_fifty_with_a_next_link(self):
        for index in range(51):
            self.add_book(f"Book {index:03}")
        root, _ = self.feed("/opds/all/")
        self.assertEqual(len(self.titles(root)), 50)
        next_link = [
            link for link in root.findall(f"{ATOM}link") if link.get("rel") == "next"
        ]
        self.assertEqual(len(next_link), 1)
        self.assertIn("page=2", next_link[0].get("href"))

        page_two, _ = self.feed("/opds/all/?page=2")
        self.assertEqual(len(self.titles(page_two)), 1)

    def test_recent_is_capped_at_fifty_newest_first(self):
        for index in range(55):
            self.add_book(f"Book {index:03}")
        root, _ = self.feed("/opds/recent/")
        titles = self.titles(root)
        self.assertEqual(len(titles), 50)
        self.assertEqual(titles[0], "Book 054")


class InboxTests(OpdsTestCase):
    def test_inbox_holds_undelivered_books_only(self):
        first = self.add_book("First")
        self.add_book("Second")
        Delivery.objects.create(book=first, device=self.device)

        root, _ = self.feed("/opds/inbox/")
        self.assertEqual(self.titles(root), ["Second"])

    def test_inbox_is_per_device(self):
        book = self.add_book("Shared")
        other_device, other_password = Device.create_with_credentials(
            self.user, "Bedroom X3"
        )
        Delivery.objects.create(book=book, device=self.device)

        root, _ = self.feed("/opds/inbox/")
        self.assertEqual(self.titles(root), [])

        response = self.client.get(
            "/opds/inbox/", headers=basic(other_device.basic_user, other_password)
        )
        other_root = ElementTree.fromstring(response.content)
        self.assertEqual(self.titles(other_root), ["Shared"])


class AcquisitionTests(OpdsTestCase):
    def test_download_sets_explicit_length_and_etag_and_records_delivery(self):
        book = self.add_book("Downloadable")
        response = self.client.get(f"/opds/book/{book.pk}.epub", headers=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/epub+zip")
        self.assertEqual(response["Content-Length"], str(book.size))
        self.assertEqual(response["ETag"], f'"{book.sha256}"')
        self.assertNotIn("Transfer-Encoding", response)
        self.assertIn('filename="b.epub"', response["Content-Disposition"])

        self.assertFalse(Delivery.objects.exists(), "not delivered until bytes leave")
        body = b"".join(response.streaming_content)
        self.assertEqual(len(body), book.size)
        self.assertTrue(
            Delivery.objects.filter(book=book, device=self.device).exists()
        )

    def test_abandoned_download_stays_in_the_inbox(self):
        book = self.add_book("Interrupted")
        response = self.client.get(f"/opds/book/{book.pk}.epub", headers=self.auth)
        # The reader drops the connection after one chunk: the WSGI server stops
        # iterating and closes the body, so the tracking generator never finishes.
        stream = _tracked(
            iter([b"a" * 100, b"b" * 100]), book.size, book.pk, self.device.pk
        )
        next(stream)
        stream.close()
        response.close()

        self.assertFalse(Delivery.objects.exists())
        root, _ = self.feed("/opds/inbox/")
        self.assertEqual(self.titles(root), ["Interrupted"])

    def test_truncated_body_is_not_a_delivery(self):
        book = self.add_book("Cut short")
        stream = _tracked(iter([b"only some bytes"]), book.size, book.pk, self.device.pk)
        list(stream)
        self.assertFalse(Delivery.objects.exists())

    def test_repeat_download_is_idempotent(self):
        book = self.add_book("Twice")
        for _ in range(2):
            response = self.client.get(f"/opds/book/{book.pk}.epub", headers=self.auth)
            b"".join(response.streaming_content)
        self.assertEqual(Delivery.objects.count(), 1)

    def test_if_none_match_returns_304_and_delivers_nothing(self):
        book = self.add_book("Cached")
        response = self.client.get(
            f"/opds/book/{book.pk}.epub",
            headers={**self.auth, "if-none-match": f'"{book.sha256}"'},
        )
        self.assertEqual(response.status_code, 304)
        self.assertFalse(Delivery.objects.exists())

    def test_another_users_book_is_not_reachable(self):
        stranger = User.objects.create_user("stranger", password="x")
        book = self.add_book("Private", owner=stranger)
        response = self.client.get(f"/opds/book/{book.pk}.epub", headers=self.auth)
        self.assertEqual(response.status_code, 404)

    def test_missing_blob_is_a_404_not_a_500(self):
        book = self.add_book("Vanished")
        book.file_path.unlink()
        with self.assertLogs("opds.views", level="ERROR"):
            response = self.client.get(f"/opds/book/{book.pk}.epub", headers=self.auth)
        self.assertEqual(response.status_code, 404)

    def test_cover_is_served_with_a_length_and_etag(self):
        book = self.add_book("Covered")
        response = self.client.get(f"/opds/cover/{book.pk}.jpg", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(
            response["Content-Length"], str(book.cover_path.stat().st_size)
        )
        self.assertEqual(response["ETag"], f'"{book.sha256}-cover"')

    def test_cover_requires_credentials(self):
        book = self.add_book("Covered")
        self.assertEqual(
            self.client.get(f"/opds/cover/{book.pk}.jpg").status_code, 401
        )
