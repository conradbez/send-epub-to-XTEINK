"""Basic auth → capability URLs.

Existing devices get a freshly minted token; there is nothing to carry over
from a password hash. Every reader must be re-pointed at its new link.
"""

import secrets

from django.db import migrations, models

from library.models import TOKEN_ALPHABET, TOKEN_LENGTH


def make_device_token():
    """Frozen here: the model's own minting function has since moved to User."""
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))


def mint_tokens(apps, schema_editor):
    Device = apps.get_model("library", "Device")
    seen = set()
    for device in Device.objects.all():
        while True:
            token = make_device_token()
            if token not in seen:
                break
        seen.add(token)
        device.token = token
        device.save(update_fields=["token"])


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="token",
            field=models.CharField(default="", max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(mint_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="device",
            name="token",
            field=models.CharField(
                default=make_device_token, max_length=64, unique=True
            ),
        ),
        migrations.RemoveField(model_name="device", name="basic_user"),
        migrations.RemoveField(model_name="device", name="pw_hash"),
    ]
