from xml.etree import ElementTree

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from library import storage
from library.ingest import ingest
from library.models import Book, User
from library.testutils import TempStorage, make_epub

from .views import _tracked

ATOM = "{http://www.w3.org/2005/Atom}"


class OpdsTestCase(TempStorage, TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reader", password="x")
        self.root = self.user.catalog_path

    def add_book(self, title="A Book", owner=None):
        payload = make_epub(title=title)
        return ingest(owner or self.user, SimpleUploadedFile("b.epub", payload)).book

    def feed(self, url, **kwargs):
        response = self.client.get(url, **kwargs)
        self.assertEqual(response.status_code, 200)
        return ElementTree.fromstring(response.content), response

    def titles(self, root):
        return [
            entry.find(f"{ATOM}title").text for entry in root.findall(f"{ATOM}entry")
        ]

    def delivered(self, book) -> bool:
        return (
            Book.objects.filter(pk=book.pk, delivered_at__isnull=False).exists()
        )


class AuthTests(OpdsTestCase):
    def test_the_token_in_the_url_is_the_whole_credential(self):
        self.add_book("Readable")
        root, _ = self.feed(self.root)
        self.assertEqual(self.titles(root)[0], "Readable")

    def test_an_unknown_token_is_a_404_not_a_challenge(self):
        response = self.client.get("/k/aaaabbbbccccdddd/")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("WWW-Authenticate", response)

    def test_a_malformed_token_does_not_even_route(self):
        for url in ("/k/", "/k/short/", "/k/UPPER-CASE-IS-NOT-A-TOKEN/"):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_a_rotated_link_kills_the_old_one(self):
        stale = self.root
        self.user.rotate_token()
        self.assertEqual(self.client.get(stale).status_code, 404)
        self.assertEqual(self.client.get(self.user.catalog_path).status_code, 200)

    def test_a_deleted_account_loses_access(self):
        self.user.delete()
        self.assertEqual(self.client.get(self.root).status_code, 404)

    def test_successful_request_records_last_seen(self):
        self.client.get(self.root)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_seen)


class RootFeedTests(OpdsTestCase):
    def test_the_root_is_the_inbox_itself_not_a_menu(self):
        self.add_book("Brand New")
        root, response = self.feed(self.root)

        self.assertIn("kind=acquisition", response["Content-Type"])
        self.assertEqual(root.find(f"{ATOM}title").text, "Inbox")
        self.assertEqual(self.titles(root)[0], "Brand New")
        self.assertTrue(response["Content-Length"])

    def test_all_books_and_recent_hang_off_the_end_of_the_inbox(self):
        self.add_book("Brand New")
        root, _ = self.feed(self.root)

        self.assertEqual(self.titles(root), ["Brand New", "All Books", "Recent"])
        subsections = {
            link.get("href")
            for link in root.iter(f"{ATOM}link")
            if link.get("rel") == "subsection"
        }
        self.assertEqual(
            subsections, {f"{self.root}all/", f"{self.root}recent/"}
        )

    def test_sub_feeds_are_only_repeated_on_the_last_page(self):
        for index in range(51):
            self.add_book(f"Book {index:03}")

        page_one, _ = self.feed(self.root)
        self.assertNotIn("All Books", self.titles(page_one))
        self.assertEqual(len(self.titles(page_one)), 50)

        page_two, _ = self.feed(f"{self.root}?page=2")
        self.assertEqual(self.titles(page_two)[-2:], ["All Books", "Recent"])


class FeedTests(OpdsTestCase):
    def test_feeds_are_well_formed_and_scoped_to_the_owner(self):
        self.add_book("Mine")
        stranger = User.objects.create_user("stranger", password="x")
        self.add_book("Theirs", owner=stranger)

        root, response = self.feed(f"{self.root}all/")
        self.assertIn("kind=acquisition", response["Content-Type"])
        self.assertEqual(self.titles(root), ["Mine"])

    def test_entry_links_carry_the_same_token(self):
        book = self.add_book("Linked")
        root, _ = self.feed(f"{self.root}all/")
        links = {link.get("rel"): link for link in root.iter(f"{ATOM}link")}

        acquisition = links["http://opds-spec.org/acquisition"]
        self.assertEqual(acquisition.get("type"), "application/epub+zip")
        self.assertEqual(acquisition.get("href"), f"{self.root}book/{book.pk}.epub")
        self.assertEqual(acquisition.get("length"), str(book.size))
        thumbnail = links["http://opds-spec.org/image/thumbnail"]
        self.assertEqual(thumbnail.get("href"), f"{self.root}cover/{book.pk}.jpg")
        self.assertEqual(links["start"].get("href"), f"http://testserver{self.root}")

    def test_acquisition_feeds_page_at_fifty_with_a_next_link(self):
        for index in range(51):
            self.add_book(f"Book {index:03}")
        root, _ = self.feed(f"{self.root}all/")
        self.assertEqual(len(self.titles(root)), 50)
        next_link = [
            link for link in root.findall(f"{ATOM}link") if link.get("rel") == "next"
        ]
        self.assertEqual(len(next_link), 1)
        self.assertIn("page=2", next_link[0].get("href"))

        page_two, _ = self.feed(f"{self.root}all/?page=2")
        self.assertEqual(len(self.titles(page_two)), 1)

    def test_recent_is_capped_at_fifty_newest_first(self):
        for index in range(55):
            self.add_book(f"Book {index:03}")
        root, _ = self.feed(f"{self.root}recent/")
        titles = self.titles(root)
        self.assertEqual(len(titles), 50)
        self.assertEqual(titles[0], "Book 054")


class InboxTests(OpdsTestCase):
    def test_inbox_holds_undelivered_books_only(self):
        first = self.add_book("First")
        self.add_book("Second")
        Book.objects.filter(pk=first.pk).update(delivered_at=timezone.now())

        root, _ = self.feed(self.root)
        self.assertEqual(self.titles(root)[0], "Second")
        self.assertNotIn("First", self.titles(root))

    def test_a_delivered_book_is_still_in_all_books(self):
        book = self.add_book("Taken")
        Book.objects.filter(pk=book.pk).update(delivered_at=timezone.now())

        root, _ = self.feed(f"{self.root}all/")
        self.assertEqual(self.titles(root), ["Taken"])


class AcquisitionTests(OpdsTestCase):
    def test_download_sets_explicit_length_and_etag_and_records_delivery(self):
        book = self.add_book("Downloadable")
        response = self.client.get(f"{self.root}book/{book.pk}.epub")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/epub+zip")
        self.assertEqual(response["Content-Length"], str(book.size))
        self.assertEqual(response["ETag"], f'"{book.sha256}"')
        self.assertNotIn("Transfer-Encoding", response)
        self.assertIn('filename="b.epub"', response["Content-Disposition"])

        self.assertFalse(self.delivered(book), "not delivered until bytes leave")
        body = b"".join(response.streaming_content)
        self.assertEqual(len(body), book.size)
        self.assertTrue(self.delivered(book))

    def test_abandoned_download_stays_in_the_inbox(self):
        book = self.add_book("Interrupted")
        response = self.client.get(f"{self.root}book/{book.pk}.epub")
        # The reader drops the connection after one chunk: the WSGI server stops
        # iterating and closes the body, so the tracking generator never finishes.
        stream = _tracked(iter([b"a" * 100, b"b" * 100]), book.size, book.pk)
        next(stream)
        stream.close()
        response.close()

        self.assertFalse(self.delivered(book))
        root, _ = self.feed(self.root)
        self.assertEqual(self.titles(root)[0], "Interrupted")

    def test_truncated_body_is_not_a_delivery(self):
        book = self.add_book("Cut short")
        list(_tracked(iter([b"only some bytes"]), book.size, book.pk))
        self.assertFalse(self.delivered(book))

    def test_repeat_download_keeps_the_first_delivery_time(self):
        book = self.add_book("Twice")
        stamps = []
        for _ in range(2):
            response = self.client.get(f"{self.root}book/{book.pk}.epub")
            b"".join(response.streaming_content)
            book.refresh_from_db()
            stamps.append(book.delivered_at)
        self.assertIsNotNone(stamps[0])
        self.assertEqual(stamps[0], stamps[1])

    def test_if_none_match_returns_304_and_delivers_nothing(self):
        book = self.add_book("Cached")
        response = self.client.get(
            f"{self.root}book/{book.pk}.epub",
            headers={"if-none-match": f'"{book.sha256}"'},
        )
        self.assertEqual(response.status_code, 304)
        self.assertFalse(self.delivered(book))

    def test_another_users_book_is_not_reachable(self):
        stranger = User.objects.create_user("stranger", password="x")
        book = self.add_book("Private", owner=stranger)
        response = self.client.get(f"{self.root}book/{book.pk}.epub")
        self.assertEqual(response.status_code, 404)

    def test_a_book_is_not_reachable_through_another_accounts_token(self):
        stranger = User.objects.create_user("stranger", password="x")
        book = self.add_book("Mine")
        response = self.client.get(f"{stranger.catalog_path}book/{book.pk}.epub")
        self.assertEqual(response.status_code, 404)

    def test_missing_blob_is_a_404_not_a_500(self):
        book = self.add_book("Vanished")
        storage.drop(book.sha256)
        with self.assertLogs("opds.views", level="ERROR"):
            response = self.client.get(f"{self.root}book/{book.pk}.epub")
        self.assertEqual(response.status_code, 404)

    def test_cover_is_served_with_a_length_and_etag(self):
        book = self.add_book("Covered")
        response = self.client.get(f"{self.root}cover/{book.pk}.jpg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(
            response["Content-Length"], str(len(storage.read_cover(book.sha256)))
        )
        self.assertEqual(response["ETag"], f'"{book.sha256}-cover"')

    def test_cover_needs_a_valid_token(self):
        book = self.add_book("Covered")
        self.assertEqual(
            self.client.get(f"/k/aaaabbbbccccdddd/cover/{book.pk}.jpg").status_code, 404
        )
