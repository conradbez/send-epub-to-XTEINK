from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Book, User

admin.site.site_header = "Library admin"
admin.site.site_title = "Library admin"


@admin.register(User)
class LibraryUserAdmin(UserAdmin):
    list_display = ("username", "last_seen", "is_staff")
    search_fields = ("username", "token")
    readonly_fields = ("token", "last_seen")
    fieldsets = UserAdmin.fieldsets + (("Reader", {"fields": ("token", "last_seen")}),)


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "owner", "size", "added_at", "delivered_at")
    list_filter = ("owner",)
    search_fields = ("title", "author", "series", "sha256")
    readonly_fields = ("sha256", "size", "added_at")
