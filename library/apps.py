from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _configure_sqlite(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")


class LibraryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "library"

    def ready(self):
        connection_created.connect(_configure_sqlite, dispatch_uid="sqlite_pragmas")
