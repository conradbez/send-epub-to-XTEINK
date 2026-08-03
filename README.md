# Personal OPDS Library

A one-way conveyor for EPUBs: upload from any browser, and the book appears in
the **Inbox** of every reader you own. No cable, no Calibre, no PC in the loop.

EPUB only. Django + SQLite on a single Railway volume. Built for one household
(~5 users, ~10 Crosspoint readers), and sized for exactly that.

## How it works

- **Upload** through `/` — one or many files, from a phone if you like.
- Each book lands on **your** shelf. Shelves are per user, not a shared pile.
- Each reader authenticates as its own **device** and sees an **Inbox**: the
  books that device has not downloaded yet. Downloading one removes it from
  that device's Inbox and nowhere else. That is what keeps an on-device catalog
  usable when the firmware has no search.
- `/help/` renders the real catalog URL, the device list, and the on-device
  steps for the account looking at it. Setting up a new reader needs nothing
  but that page.

## Local development

```sh
uv venv --python 3.13
uv pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Data lands in `./data/` (`library.db`, `books/`, `covers/`, `tmp/`). Override
with `DATA_DIR`.

Run the tests:

```sh
.venv/bin/python manage.py test
```

## Layout

```
config/    settings, urls, wsgi
library/   models, upload pipeline, EPUB parsing, management commands
opds/      Atom feeds, Basic-auth decorator, delivery tracking
web/       shelf, devices, /help/
```

Dependencies, complete: `django`, `gunicorn`, `whitenoise`, `pillow`. EPUB
parsing is stdlib `zipfile` + `xml.etree`.

## Deployment (Railway)

1. New service from this repo. **`replicas = 1`, non-negotiable** — SQLite has
   one writer and the volume binds to one service.
2. Attach a volume at `/data`. 5 GB holds roughly 1,500 EPUBs.
3. Variables: `SECRET_KEY`, `ALLOWED_HOSTS`, `DATA_DIR=/data`, `DEBUG=0`.
   `RAILWAY_PUBLIC_DOMAIN` is picked up automatically for CSRF and hosts; a
   custom domain needs `CSRF_TRUSTED_ORIGINS` too.
4. Create users in `/admin/`, then send each person to `/help/`.

The start command runs `migrate` and `collectstatic` before gunicorn, so a
deploy needs no manual step.

### Backups — do not skip this

The Railway volume is **not snapshotted**. If it goes, the library goes.

```sh
python manage.py backup            # VACUUM INTO a snapshot + tar the blobs
python manage.py backup --skip-books   # database only, much faster
```

Set `BACKUP_UPLOAD_CMD` to push each artefact off-box, e.g.
`rclone copy {path} r2:library-backups/`. Without it the command warns and
leaves the snapshots on the same volume a bad deploy would destroy. Run it
nightly from a Railway cron service:

```
python manage.py backup && python manage.py sweep_tmp
```

`sweep_tmp` clears upload fragments left by a crash mid-upload.

## Readers

- **Firmware v1.3.0 or newer is required.** Older builds run out of memory
  during the TLS handshake and cannot reach an HTTPS host at all. If the
  handshake is a problem, the same container runs fine on a LAN box over plain
  HTTP.
- Firmware 1.5.0+ can configure the OPDS download folder and filename format.

## Deliberately not here

Comics, audiobooks, PDF, metadata scraping, email ingest, federation, and
reading-progress sync. Crosspoint already syncs progress through its own
KOReader-compatible server; that stays a separate concern.
