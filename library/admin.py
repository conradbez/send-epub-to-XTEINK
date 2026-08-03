from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Book, Delivery, Device, User

admin.site.site_header = "Library admin"
admin.site.site_title = "Library admin"


@admin.register(User)
class LibraryUserAdmin(UserAdmin):
    pass


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "basic_user", "user", "last_seen", "created_at")
    list_filter = ("user",)
    search_fields = ("name", "basic_user")
    readonly_fields = ("pw_hash", "last_seen", "created_at")


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "owner", "size", "added_at")
    list_filter = ("owner",)
    search_fields = ("title", "author", "series", "sha256")
    readonly_fields = ("sha256", "size", "added_at")


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ("book", "device", "downloaded_at")
    list_filter = ("device",)
