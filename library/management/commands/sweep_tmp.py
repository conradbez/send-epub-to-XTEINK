"""Delete abandoned upload fragments. A crash mid-upload leaves them behind."""

import time

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Remove files in the tmp directory older than --hours (default 24)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=float, default=24.0)

    def handle(self, *args, **options):
        cutoff = time.time() - options["hours"] * 3600
        removed = freed = 0
        for path in settings.TMP_DIR.iterdir():
            if not path.is_file():
                continue
            try:
                stat = path.stat()
                if stat.st_mtime < cutoff:
                    path.unlink()
                    removed += 1
                    freed += stat.st_size
            except OSError as exc:
                self.stderr.write(f"skip {path.name}: {exc}")
        self.stdout.write(f"removed {removed} file(s), {freed / 1e6:.1f} MB")
