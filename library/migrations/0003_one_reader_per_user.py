"""Collapse Device into User: one account, one reader.

Every account had a list of devices in practice holding exactly one. The token
and the Inbox move onto the objects that already existed — the user and the
book — and Device and Delivery go away.

An account with several devices keeps the first one's link (by name, the order
/devices/ showed them in); the rest stop working and have nothing to carry over.
A book counts as delivered if *any* device had taken it.
"""

from django.db import migrations, models

import library.models


def collapse(apps, schema_editor):
    User = apps.get_model("library", "User")
    Device = apps.get_model("library", "Device")
    Book = apps.get_model("library", "Book")
    Delivery = apps.get_model("library", "Delivery")

    taken = set()
    for user in User.objects.all():
        device = Device.objects.filter(user=user).order_by("name", "pk").first()
        if device is not None and device.token not in taken:
            user.token = device.token
            user.last_seen = device.last_seen
        else:
            while True:
                candidate = library.models.make_token()
                if candidate not in taken:
                    break
            user.token = candidate
        taken.add(user.token)
        user.save(update_fields=["token", "last_seen"])

    for book_id, downloaded_at in Delivery.objects.order_by(
        "book_id", "downloaded_at"
    ).values_list("book_id", "downloaded_at"):
        Book.objects.filter(pk=book_id, delivered_at__isnull=True).update(
            delivered_at=downloaded_at
        )


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0002_device_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="token",
            field=models.CharField(default="", max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="user",
            name="last_seen",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="book",
            name="delivered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(collapse, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="token",
            field=models.CharField(
                default=library.models.make_token, max_length=64, unique=True
            ),
        ),
        migrations.RemoveConstraint(
            model_name="delivery",
            name="uniq_book_device",
        ),
        migrations.DeleteModel(name="Delivery"),
        migrations.DeleteModel(name="Device"),
    ]
