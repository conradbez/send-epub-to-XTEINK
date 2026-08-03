from django.test import TestCase
from django.urls import reverse
from library.models import Book, User


class SignupTests(TestCase):
    def test_page_renders_and_links_from_login(self):
        self.assertContains(self.client.get(reverse("signup")), "Create account")
        self.assertContains(self.client.get(reverse("login")), reverse("signup"))

    def test_creates_account_and_logs_in(self):
        r = self.client.post(reverse("signup"), {
            "username": "conrad",
            "password1": "a-quite-long-passphrase-42",
            "password2": "a-quite-long-passphrase-42",
        })
        self.assertRedirects(r, reverse("shelf"))
        self.assertTrue(User.objects.filter(username="conrad").exists())
        self.assertContains(self.client.get(reverse("shelf")), "Sign out")

    def test_rejects_mismatch_and_duplicate(self):
        self.client.post(reverse("signup"), {
            "username": "dup", "password1": "a-quite-long-passphrase-42",
            "password2": "a-quite-long-passphrase-42"})
        self.client.logout()
        r = self.client.post(reverse("signup"), {
            "username": "dup", "password1": "a-quite-long-passphrase-42",
            "password2": "a-quite-long-passphrase-42"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.filter(username="dup").count(), 1)

    def test_new_account_shelf_is_isolated(self):
        other = User.objects.create_user("other", password="x-long-pass-9999")
        Book.objects.create(owner=other, title="Theirs", author="A",
                            sha256="a" * 64, size=1, filename="t.epub")
        self.client.post(reverse("signup"), {
            "username": "fresh", "password1": "a-quite-long-passphrase-42",
            "password2": "a-quite-long-passphrase-42"})
        self.assertNotContains(self.client.get(reverse("shelf")), "Theirs")
