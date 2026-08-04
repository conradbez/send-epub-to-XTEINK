"""Django settings for the personal OPDS library."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Core -------------------------------------------------------------------

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-do-not-use-in-production")
DEBUG = os.environ.get("DEBUG", "1") == "1"

ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]

CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o
]
# Railway injects the public domain; trust it without needing a second env var.
_railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
if _railway_domain:
    if _railway_domain not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_railway_domain)
    origin = f"https://{_railway_domain}"
    if origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)

# Railway terminates TLS in front of us.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# --- Storage on the volume --------------------------------------------------

# Books live in the database file, not beside it; the volume holds that file and
# the temp directory an upload passes through on its way in.
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
TMP_DIR = DATA_DIR / "tmp"
for _d in (DATA_DIR, TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Per file, not per shelf: one book may be this big, and a shelf may hold as
# many of them as the volume does.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
COVER_LONG_EDGE = 200
OPDS_PAGE_SIZE = 50

# Uploads land on the volume as temp files rather than in memory, so the
# pipeline can stream them without ever holding a whole book in RAM.
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_TEMP_DIR = str(TMP_DIR)

# --- Apps -------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "library",
    "opds",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---------------------------------------------------------------

# The database holds the books themselves, so a download is a long-lived reader
# and an upload is a multi-megabyte writer. WAL is what lets those two coexist:
# without it a download in progress would block every upload behind it until the
# reader finished, or until the timeout gave up. IMMEDIATE takes the write lock
# at BEGIN rather than discovering it is needed halfway through.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "library.db",
        "OPTIONS": {
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "transaction_mode": "IMMEDIATE",
        },
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "library.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "shelf"
LOGOUT_REDIRECT_URL = "login"

# --- i18n / static ----------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # The hashed manifest needs collectstatic to have run; in development
        # (and in tests, which force DEBUG off after import) serve files as-is.
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# --- Backups ----------------------------------------------------------------

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", DATA_DIR / "backup"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
