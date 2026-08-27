import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

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

BEHIND_HTTPS_PROXY = (
    os.environ.get("DJANGO_BEHIND_HTTPS_PROXY", "0") == "1"
)

if BEHIND_HTTPS_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Explicit development/demo-data opt-in for TASK_027's bootstrap_demo_data
# command. Disabled by default; only the literal string "1" enables it — no
# DEBUG or hostname heuristic, so turning it on requires a deliberate
# environment change, never an accident of running with DEBUG=1. See
# TASK_027 §4.
ENABLE_DEMO_DATA = os.environ.get("PRICEWATCHPH_ENABLE_DEMO_DATA", "0") == "1"

# TASK_031: outbound Telegram alerting is opt-in, matching ENABLE_DEMO_DATA's
# literal-"1"-only convention — no DEBUG or hostname heuristic. The other
# four values are read raw here and validated lazily by
# alerts.config.load_alert_config(), never at settings-import time, so
# importing settings with alerts disabled never requires them to be set.
ENABLE_ALERTS = os.environ.get("PRICEWATCHPH_ENABLE_ALERTS", "0") == "1"
TELEGRAM_BOT_TOKEN = os.environ.get("PRICEWATCHPH_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("PRICEWATCHPH_TELEGRAM_CHAT_ID", "")
ALERT_ACTIVATION_AT = os.environ.get("PRICEWATCHPH_ALERT_ACTIVATION_AT", "")
PUBLIC_BASE_URL = os.environ.get("PRICEWATCHPH_PUBLIC_BASE_URL", "")

# An HTTPS public origin is unsafe unless Django trusts the terminating proxy.
if urlsplit(PUBLIC_BASE_URL).scheme.lower() == "https" and not BEHIND_HTTPS_PROXY:
    raise ImproperlyConfigured(
        "PRICEWATCHPH_PUBLIC_BASE_URL uses HTTPS, so "
        'DJANGO_BEHIND_HTTPS_PROXY must be the literal string "1".'
    )

# TASK_036 validates this deployment cadence in the standalone scheduler.
SCHEDULER_CRON = os.environ.get("PRICEWATCHPH_SCHEDULER_CRON", "")

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
    "axes",
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
    "axes.middleware.AxesMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# PostgreSQL keeps one restart-persistent throttle across Gunicorn workers.
AXES_HANDLER = "axes.handlers.database.AxesDatabaseHandler"
AXES_LOCKOUT_PARAMETERS = ["ip_address"]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_USE_ATTEMPT_EXPIRATION = True
AXES_RESET_ON_SUCCESS = True
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = False
AXES_HTTP_RESPONSE_CODE = 429
AXES_COOLOFF_MESSAGE = "Too many login attempts. Please try again later."

AXES_DISABLE_ACCESS_LOG = True
AXES_ENABLE_ACCESS_FAILURE_LOG = False
AXES_ENABLE_ADMIN = False
AXES_SENSITIVE_PARAMETERS = ["username", "ip_address"]
AXES_ONLY_ADMIN_SITE = False

# Caddy replaces X-Forwarded-For; direct/local requests must ignore it.
AXES_IPWARE_PROXY_ORDER = "left-most"
AXES_IPWARE_PROXY_COUNT = 0
AXES_IPWARE_META_PRECEDENCE_ORDER = (
    ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")
    if BEHIND_HTTPS_PROXY
    else ("REMOTE_ADDR",)
)

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
