import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# No hardcoded fallback: CLAUDE.md requires secrets to come from the
# environment only, so a missing key must fail loudly, not fall back silently.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# Same fail-loudly rule as SECRET_KEY. This key can never be rotated: tokens
# derived from it live in immutable RawListing rows, so a new key stops
# matching a counterparty's past tokens and silently breaks repeat-
# counterparty linkage. Backup-critical for the life of the database. See
# TASK_005 Decision 6.
SELLER_PSEUDONYM_KEY = os.environ["DJANGO_SELLER_PSEUDONYM_KEY"]

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

# Explicit development/demo-data opt-in for TASK_027's bootstrap_demo_data
# command. Disabled by default; only the literal string "1" enables it — no
# DEBUG or hostname heuristic, so turning it on requires a deliberate
# environment change, never an accident of running with DEBUG=1. See
# TASK_027 §4.
ENABLE_DEMO_DATA = os.environ.get("PRICEWATCHPH_ENABLE_DEMO_DATA", "0") == "1"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "sources",
    "catalogue",
    "ingestion",
    "listings",
    "pricing",
    "outcomes",
    "alerts",
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

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.environ["POSTGRES_PORT"],
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"

# Vite owns its hashed filenames, so static collection must preserve them.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

# The prefix keeps Vite assets separate from Django and admin static files.
STATICFILES_DIRS = (
    [("frontend", FRONTEND_DIST_DIR)]
    if FRONTEND_DIST_DIR.is_dir()
    else []
)

LOGIN_REDIRECT_URL = "/deals"
LOGOUT_REDIRECT_URL = "/auth/login/"

# Storage timezone is UTC everywhere; USE_TZ makes Django store
# timezone-aware datetimes rather than naive ones.
USE_TZ = True
TIME_ZONE = "UTC"

# Display-only setting for templates/views to convert into later. Never used
# for storage or for Django's own TIME_ZONE — those two must never merge.
DISPLAY_TIME_ZONE = os.environ.get("DJANGO_DISPLAY_TIME_ZONE", "Asia/Manila")

# The day-bucketing boundary PricePoint.day derives from (via
# pricing.bucketing.manila_day) is a third timezone decision, distinct from
# storage (UTC) and display. Unlike DISPLAY_TIME_ZONE this is a hardcoded
# constant, not read from the environment: changing it would silently
# rebucket every stored PricePoint, which must be a deliberate code change
# with a migration plan, not an env tweak on one machine. See TASK_005
# Decision 3.
AGGREGATION_TIME_ZONE = "Asia/Manila"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "api.pagination.FixedPageNumberPagination",
    "PAGE_SIZE": 25,
    "COERCE_DECIMAL_TO_STRING": True,
}
