import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from library.ingest import ingest
from library.models import Book, Device, User
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
        for url in ("/", "/devices/", "/help/"):
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

    def test_filter_matches_title_and_author(self):
        self.add_book("Dune")
        self.add_book("Neuromancer")
        response = self.client.get("/", {"q": "dune"})
        self.assertContains(response, "Dune")
        self.assertNotContains(response, "Neuromancer")

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


class DeviceTests(WebTestCase):
    def test_creating_a_device_shows_the_password_exactly_once(self):
        response = self.client.post("/devices/", {"name": "Lounge X4"}, follow=True)
        device = Device.objects.get()
        password = response.context["new_credential"]["password"]

        self.assertContains(response, device.basic_user)
        self.assertContains(response, password)
        self.assertTrue(device.check_device_password(password))

        again = self.client.get("/devices/")
        self.assertNotContains(again, password)

    def test_reset_issues_a_new_password_and_kills_the_old_one(self):
        first = self.client.post("/devices/", {"name": "X3"}, follow=True)
        device = Device.objects.get()
        old = first.context["new_credential"]["password"]

        second = self.client.post(f"/devices/{device.pk}/reset/", follow=True)
        new = second.context["new_credential"]["password"]

        device.refresh_from_db()
        self.assertNotEqual(old, new)
        self.assertFalse(device.check_device_password(old))
        self.assertTrue(device.check_device_password(new))

    def test_rename_and_revoke(self):
        self.client.post("/devices/", {"name": "Old name"}, follow=True)
        device = Device.objects.get()

        self.client.post(f"/devices/{device.pk}/rename/", {"name": "Lounge X4"})
        device.refresh_from_db()
        self.assertEqual(device.name, "Lounge X4")

        self.client.post(f"/devices/{device.pk}/revoke/", follow=True)
        self.assertEqual(Device.objects.count(), 0)

    def test_cannot_touch_another_users_device(self):
        stranger = User.objects.create_user("stranger", password="x")
        device, _ = Device.create_with_credentials(stranger, "Not yours")
        for url in (f"/devices/{device.pk}/reset/", f"/devices/{device.pk}/revoke/"):
            self.assertEqual(self.client.post(url).status_code, 404)


class HelpPageTests(WebTestCase):
    def test_shows_the_real_catalog_url_not_a_placeholder(self):
        response = self.client.get("/help/")
        self.assertContains(response, "http://testserver/opds/")
        self.assertNotContains(response, "example.com")

    def test_lists_devices_with_usernames_but_never_a_password(self):
        device, password = Device.create_with_credentials(self.user, "Lounge X4")
        response = self.client.get("/help/")
        self.assertContains(response, "Lounge X4")
        self.assertContains(response, device.basic_user)
        self.assertNotContains(response, password)
        self.assertContains(response, "Reset password")

    def test_covers_the_questions_people_would_otherwise_ask(self):
        response = self.client.get("/help/")
        content = response.content.decode()
        self.assertIn("v1.3.0", content)          # TLS handshake OOM
        self.assertIn("All Books", content)       # re-download after Inbox
        self.assertIn("EPUB only", content)       # nothing else is accepted
        self.assertIn("Settings", content)        # on-device steps

    def test_reports_storage_use(self):
        self.add_book("Weighty")
        response = self.client.get("/help/")
        self.assertEqual(response.context["book_count"], 1)
        self.assertGreater(response.context["blob_bytes"], 0)
        self.assertIn("Volume", response.content.decode())
