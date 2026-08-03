"""Nightly backup: the volume is not snapshotted, so this is the only copy.

Produces a consistent database snapshot with VACUUM INTO (safe against a live
writer, unlike copying the file) and a tar of the blobs, then hands both to
BACKUP_UPLOAD_CMD if one is configured — e.g.

    BACKUP_UPLOAD_CMD='rclone copy {path} r2:library-backups/'

The command is run without a shell; {path} is substituted per file.
"""

import datetime
import os
import shlex
import subprocess
import tarfile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Snapshot the database and books, then push off-box."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-books",
            action="store_true",
            help="Database only; the blob tar dominates the runtime.",
        )
        parser.add_argument("--keep", type=int, default=7, help="Local snapshots kept.")

    def handle(self, *args, **options):
        out_dir = settings.BACKUP_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

        db_path = out_dir / f"library-{stamp}.db"
        with connection.cursor() as cursor:
            cursor.execute("VACUUM INTO %s", [str(db_path)])
        self.stdout.write(f"database → {db_path} ({db_path.stat().st_size / 1e6:.1f} MB)")
        artefacts = [db_path]

        if not options["skip_books"]:
            tar_path = out_dir / f"books-{stamp}.tar"
            with tarfile.open(tar_path, "w") as tar:
                tar.add(settings.BOOKS_DIR, arcname="books")
                if settings.COVERS_DIR.exists():
                    tar.add(settings.COVERS_DIR, arcname="covers")
            self.stdout.write(
                f"blobs → {tar_path} ({tar_path.stat().st_size / 1e6:.1f} MB)"
            )
            artefacts.append(tar_path)

        template = os.environ.get("BACKUP_UPLOAD_CMD", "").strip()
        if template:
            for path in artefacts:
                argv = [
                    part.replace("{path}", str(path)) for part in shlex.split(template)
                ]
                completed = subprocess.run(argv, capture_output=True, text=True)
                if completed.returncode != 0:
                    raise CommandError(
                        f"upload failed for {path.name}: {completed.stderr.strip()}"
                    )
                self.stdout.write(f"uploaded {path.name}")
        else:
            self.stdout.write(
                self.style.WARNING(
                    "BACKUP_UPLOAD_CMD is not set — snapshots stayed on the volume, "
                    "which is the thing a bad deploy destroys."
                )
            )

        self._prune(out_dir, options["keep"])

    def _prune(self, out_dir, keep: int):
        for prefix in ("library-", "books-"):
            snapshots = sorted(
                (p for p in out_dir.iterdir() if p.name.startswith(prefix)),
                reverse=True,
            )
            for stale in snapshots[keep:]:
                stale.unlink()
                self.stdout.write(f"pruned {stale.name}")
