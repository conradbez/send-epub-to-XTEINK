from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from library.ingest import ingest
from library.models import Book, User
from library.testutils import TempStorage, make_epub


class WebTestCase(TempStorage, TestCase):
    def setUp(self):
        self.user = User.objects.create_user("conrad", password="hunter2hunter2")
        self.client.force_login(self.user)

    def add_book(self, title="A Book", owner=None):
        return ingest(
            owner or self.user, SimpleUploadedFile("b.epub", make_epub(title=title))
        ).book


class AccessTests(WebTestCase):
    def test_every_page_needs_a_session(self):
        self.client.logout()
        for url in ("/", "/help/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login/", response["Location"])


class UploadTests(WebTestCase):
    def test_uploading_two_books_puts_both_on_the_shelf(self):
        files = [
            SimpleUploadedFile("one.epub", make_epub(title="One")),
            SimpleUploadedFile("two.epub", make_epub(title="Two")),
        ]
        response = self.client.post("/upload/", {"epub": files}, follow=True)
        self.assertEqual(Book.objects.filter(owner=self.user).count(), 2)
        self.assertContains(response, "Added 2 books")
        self.assertContains(response, "One")

    def test_a_rejected_file_reports_why(self):
        bogus = SimpleUploadedFile("notes.epub", b"just some text")
        response = self.client.post("/upload/", {"epub": bogus}, follow=True)
        self.assertEqual(Book.objects.count(), 0)
        self.assertContains(response, "notes.epub")

    def test_mixed_batch_keeps_the_good_one(self):
        files = [
            SimpleUploadedFile("good.epub", make_epub(title="Good")),
            SimpleUploadedFile("bad.epub", b"nope"),
        ]
        response = self.client.post("/upload/", {"epub": files}, follow=True)
        self.assertEqual(Book.objects.count(), 1)
        self.assertContains(response, "Added 1 book")
        self.assertContains(response, "bad.epub")


class ShelfTests(WebTestCase):
    def test_shelf_shows_only_your_books(self):
        self.add_book("Mine")
        stranger = User.objects.create_user("stranger", password="x")
        self.add_book("Theirs", owner=stranger)

        response = self.client.get("/")
        self.assertContains(response, "Mine")
        self.assertNotContains(response, "Theirs")

    def test_delete_removes_the_book(self):
        book = self.add_book("Doomed")
        response = self.client.post(f"/book/{book.pk}/delete/", follow=True)
        self.assertEqual(Book.objects.count(), 0)
        self.assertContains(response, "Removed")

    def test_cannot_delete_someone_elses_book(self):
        stranger = User.objects.create_user("stranger", password="x")
        book = self.add_book("Theirs", owner=stranger)
        self.assertEqual(
            self.client.post(f"/book/{book.pk}/delete/").status_code, 404
        )
        self.assertEqual(Book.objects.count(), 1)

    def test_cover_is_scoped_to_the_owner(self):
        book = self.add_book("Covered")
        self.assertEqual(
            self.client.get(f"/book/{book.pk}/cover.jpg").status_code, 200
        )
        self.client.force_login(User.objects.create_user("stranger", password="x"))
        self.assertEqual(
            self.client.get(f"/book/{book.pk}/cover.jpg").status_code, 404
        )


class CatalogLinkTests(WebTestCase):
    def test_an_account_has_a_link_from_the_moment_it_exists(self):
        response = self.client.get("/help/")
        self.assertContains(response, f"http://testserver/k/{self.user.token}/")

    def test_the_link_stays_visible_there_is_nothing_to_write_down(self):
        for _ in range(2):
            self.assertContains(self.client.get("/help/"), self.user.token)

    def test_reset_issues_a_new_link_and_kills_the_old_one(self):
        old = self.user.token

        response = self.client.post("/help/new-link/", follow=True)

        self.user.refresh_from_db()
        self.assertNotEqual(old, self.user.token)
        self.assertNotContains(response, old)
        self.assertContains(response, self.user.token)

    def test_reset_puts_the_whole_shelf_back_in_the_inbox(self):
        """A new link means a new reader, and it holds none of the books yet."""
        delivered = self.add_book("Already Read")
        Book.objects.filter(pk=delivered.pk).update(delivered_at=timezone.now())

        self.client.post("/help/new-link/", follow=True)

        delivered.refresh_from_db()
        self.assertIsNone(delivered.delivered_at)

    def test_reset_leaves_another_users_deliveries_alone(self):
        stranger = User.objects.create_user("stranger", password="x")
        theirs = self.add_book("Theirs", owner=stranger)
        stamped = timezone.now()
        Book.objects.filter(pk=theirs.pk).update(delivered_at=stamped)

        self.client.post("/help/new-link/", follow=True)

        theirs.refresh_from_db()
        self.assertEqual(theirs.delivered_at, stamped)

    def test_another_users_link_is_never_shown(self):
        stranger = User.objects.create_user("stranger", password="x")
        self.assertNotContains(self.client.get("/help/"), stranger.token)


class HelpPageTests(WebTestCase):
    def test_shows_a_real_pastable_link_not_a_placeholder(self):
        response = self.client.get("/help/")

        self.assertContains(response, f"http://testserver/k/{self.user.token}/")
        self.assertNotContains(response, "example.com")

    def test_the_copy_button_carries_the_url(self):
        response = self.client.get("/help/")
        self.assertContains(
            response, f'data-copy="http://testserver/k/{self.user.token}/">Copy'
        )

    def test_copy_the_link_comes_before_pasting_it(self):
        content = self.client.get("/help/").content.decode()
        self.assertLess(
            content.index("Copy your link"),
            content.index("Paste it into the reader"),
        )
        self.assertIn("File Transfer", content)   # how the reader's web UI opens
        self.assertIn("OPDS Servers", content)    # the card you paste into

    def test_covers_the_questions_people_would_otherwise_ask(self):
        response = self.client.get("/help/")
        content = response.content.decode()
        self.assertIn("v1.3.0", content)          # TLS handshake OOM
        self.assertIn("Inbox", content)           # what the reader opens on
        self.assertIn("EPUB only", content)       # nothing else is accepted

    def test_reports_storage_use(self):
        self.add_book("Weighty")
        response = self.client.get("/help/")
        self.assertEqual(response.context["book_count"], 1)
        self.assertGreater(response.context["blob_bytes"], 0)
        self.assertIn("1 book on your shelf", response.content.decode())
