"""Books move off the volume and into the database.

Nothing is carried over: blobs already sitting in data/books and data/covers
stay there, unread, and any Book row from before this point now points at bytes
the database does not have. Those rows still list and still delete; downloading
one is a 404. Delete them from the shelf and upload again, or start from an
empty data directory.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0003_one_reader_per_user'),
    ]

    operations = [
        migrations.CreateModel(
            name='Blob',
            fields=[
                ('sha256', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('size', models.BigIntegerField()),
                ('data', models.BinaryField()),
                ('cover', models.BinaryField(blank=True, null=True)),
            ],
        ),
    ]
