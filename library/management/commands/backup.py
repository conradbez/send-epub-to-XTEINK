"""Nightly backup: the volume is not snapshotted, so this is the only copy.

The books live in the database, so one artefact is the whole library. VACUUM
INTO writes a consistent snapshot while the site is running (unlike copying the
file) and compacts it on the way out, reclaiming the pages that deleted books
left behind. The snapshot then goes to BACKUP_UPLOAD_CMD if one is configured —

    BACKUP_UPLOAD_CMD='rclone copy {path} r2:library-backups/'

The command is run without a shell; {path} is substituted per file.
"""

import datetime
import os
import shlex
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Snapshot the database — books included — then push it off-box."

    def add_arguments(self, parser):
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
        snapshots = sorted(
            (p for p in out_dir.iterdir() if p.name.startswith("library-")),
            reverse=True,
        )
        for stale in snapshots[keep:]:
            stale.unlink()
            self.stdout.write(f"pruned {stale.name}")
