"""
Django settings for the Portal backend.

Everything environment-specific comes from environment variables (see
.env.example). For local development: `cp .env.example .env`.
"""
import os
from pathlib import Path

import dj_database_url
from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
# Separate secret for hashing verification codes (see common/codes.py).
OTP_HMAC_KEY = os.environ.get("OTP_HMAC_KEY", "")
if DEBUG:
    SECRET_KEY = SECRET_KEY or "dev-only-insecure-secret-key-do-not-use-in-production"
    OTP_HMAC_KEY = OTP_HMAC_KEY or "dev-only-insecure-otp-hmac-key-do-not-use-in-production"
elif not SECRET_KEY or not OTP_HMAC_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY and OTP_HMAC_KEY when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")

# The React app is served from the same origin as /api (Vite proxies /api in
# development; a reverse proxy does it in production), so no CORS is needed.
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173," if DEBUG else "",
)

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "messaging",
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
        "DIRS": [BASE_DIR / "templates"],  # admin dashboard override lives here
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

# ---------------------------------------------------------------------------
# Database / cache / Redis
# ---------------------------------------------------------------------------
# PostgreSQL in real use (DATABASE_URL), SQLite only as a zero-config fallback.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
        conn_health_checks=True,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
# The SPA reads the CSRF cookie and echoes it in X-CSRFToken, so it must not be HttpOnly.
CSRF_COOKIE_HTTPONLY = False

# ---------------------------------------------------------------------------
# REST framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    # Blanket limits. Sensitive flows (sign-up, login, OTP) add their own,
    # finer-grained limits on top (see common/ratelimit.py).
    "DEFAULT_THROTTLE_RATES": {"anon": "120/min", "user": "600/min"},
    "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = REDIS_URL
# In development tasks run inline, so no worker process is needed.
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", DEBUG)
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_TIME_LIMIT = 60
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
# So a crontab schedule below at "7am" means 7am in Ghana, not UTC.
CELERY_TIMEZONE = "Africa/Accra"
# Requires a beat process running: celery -A config beat -l info
CELERY_BEAT_SCHEDULE = {
    "send-birthday-messages": {
        "task": "messaging.tasks.send_birthday_messages_task",
        "schedule": crontab(hour=7, minute=0),
    },
}

# ---------------------------------------------------------------------------
# Product settings
# ---------------------------------------------------------------------------
APP_NAME = os.environ.get("APP_NAME", "Portal")

# Alphanumeric sender ID for platform messages (sign-up codes). Max 11 characters.
DEFAULT_SENDER_ID = os.environ.get("DEFAULT_SENDER_ID", "Portal")
if len(DEFAULT_SENDER_ID) > 11:
    raise ImproperlyConfigured("DEFAULT_SENDER_ID must be 11 characters or fewer.")

# console: prints messages to the server log (development only)
# arkesel: sends through Arkesel's HTTP API

SMS_BACKEND = os.environ.get(
    "SMS_BACKEND",
    "console" if DEBUG else "arkesel"
).strip().lower()

if not DEBUG and SMS_BACKEND in {"console", "memory"}:
    raise ImproperlyConfigured(
        "Production must use a real SMS provider."
    )


ARKESEL_API_KEY = os.environ.get("ARKESEL_API_KEY", "").strip()

ARKESEL_SMS_URL = os.environ.get(
    "ARKESEL_SMS_URL",
    "https://sms.arkesel.com/api/v2/sms/send"
)

ARKESEL_SANDBOX = env_bool("ARKESEL_SANDBOX", False)

# Dexatel: https://developers.dexatel.com/reference/messages-send. DEFAULT_SENDER_ID
# doubles as the Dexatel "from" value, so it needs to be a sender name registered
# with Dexatel too, same as it needs to be registered with Arkesel.
DEXATEL_API_KEY = os.environ.get("DEXATEL_API_KEY", "")
DEXATEL_SMS_URL = os.environ.get("DEXATEL_SMS_URL", "https://api.dexatel.com/v1/messages")

# Delivery reports: Arkesel's send API only confirms "accepted", never
# "actually reached the phone" - that only comes later, as a callback to this
# server. ARKESEL_DLR_SECRET gates that callback URL (Arkesel has no request
# signature, so the secret path segment is the only proof it's really them);
# BACKEND_URL lets us hand Arkesel the full callback URL on every send instead
# of relying solely on whatever's configured in the Arkesel dashboard. Leave
# either unset and delivery reports are simply not requested/accepted -
# messages still send, they just stay at "sent" instead of ever reaching
# "delivered". See messaging/webhooks.py and the README for setup.
ARKESEL_DLR_SECRET = os.environ.get("ARKESEL_DLR_SECRET", "")
BACKEND_URL = os.environ.get("BACKEND_URL", "").rstrip("/")

# Text the new account owner a welcome message right after sign-up verification
# succeeds (platform-sent, not billed to their wallet). Failures never block sign-up.
WELCOME_SMS_ENABLED = env_bool("WELCOME_SMS_ENABLED", True)


# Text the admins when someone creates an account. Recipients: every active
# staff/superuser who has a phone number on their profile (set it in the admin),
# plus any extra numbers listed in ADMIN_ALERT_PHONES (comma separated, e.g.
# "024 123 4567,0551234567"). Failures never block sign-up.
ADMIN_SIGNUP_ALERTS_ENABLED = env_bool("ADMIN_SIGNUP_ALERTS_ENABLED", True)
ADMIN_ALERT_PHONES = env_list("ADMIN_ALERT_PHONES")

# Wallet top-ups. Paystack's hosted checkout page takes the payment, so card and
# Mobile Money details never touch this server. Use the secret key from
# Paystack's dashboard (sk_test_... while testing, sk_live_... for real money).
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_API_URL = os.environ.get("PAYSTACK_API_URL", "https://api.paystack.co")
# Where Paystack sends people after paying. Must be the address the React app is served from.
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173" if DEBUG else "").rstrip("/")
if not DEBUG and PAYSTACK_SECRET_KEY and not FRONTEND_URL:
    raise ImproperlyConfigured("Set FRONTEND_URL when PAYSTACK_SECRET_KEY is set and DJANGO_DEBUG is off.")
# Bounds for a custom top-up amount, in pesewas (100 = GHS 1).
TOPUP_MIN_PESEWAS = env_int("TOPUP_MIN_PESEWAS", 500)          # GHS 5
TOPUP_MAX_PESEWAS = env_int("TOPUP_MAX_PESEWAS", 1_000_000)    # GHS 10,000

# Welcome credit (pesewas) added to a new account's wallet. 100 pesewas = GHS 1.
SIGNUP_BONUS_PESEWAS = env_int("SIGNUP_BONUS_PESEWAS", 0)
# Used when no PricingTier row exists.
DEFAULT_PRICE_PER_SEGMENT_PESEWAS = env_int("DEFAULT_PRICE_PER_SEGMENT_PESEWAS", 5)
# Hard ceiling on sign-up verification SMS per day, so abuse can't run up a bill.
SIGNUP_SMS_DAILY_CAP = env_int("SIGNUP_SMS_DAILY_CAP", 1000)
# Reverse proxies in front of Django (see common/ratelimit.client_ip). 0 = none.
TRUSTED_PROXY_COUNT = env_int("TRUSTED_PROXY_COUNT", 0)

# ---------------------------------------------------------------------------
# i18n / static
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Accra"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}




# ---------------------------------------------------------------------------
# Production hardening
# ---------------------------------------------------------------------------
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)  # raise once HTTPS is confirmed working
    SECURE_CONTENT_TYPE_NOSNIFF = True
    if env_bool("BEHIND_TLS_PROXY", True):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}



# ---------------------------------------------------------------------------
# Admin site (django-unfold). Brand colours match the React app: forest green + gold.
# ---------------------------------------------------------------------------
from django.templatetags.static import static  # noqa: E402
from django.urls import reverse_lazy  # noqa: E402


def _nav_item(title, icon, model):
    return {"title": title, "icon": icon, "link": reverse_lazy(f"admin:messaging_{model}_changelist")}


# Unfold's login form omits Django's hidden "next" field, so opening /admin/login/
# directly would otherwise land on the default /accounts/profile/ (a 404) after
# signing in. Only the admin uses Django's session login; the React app has its own API auth.
LOGIN_REDIRECT_URL = "/admin/"

UNFOLD = {
    "SITE_TITLE": f"{APP_NAME} admin",
    "SITE_HEADER": f"{APP_NAME}",
    "SITE_SUBHEADER": "Operations",
    "SITE_URL": "/",
    "SITE_ICON": lambda request: static("messaging/portal-mark.svg"),
    "SITE_FAVICONS": [{"rel": "icon", "sizes": "32x32", "type": "image/svg+xml",
                       "href": lambda request: static("messaging/portal-mark.svg")}],
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "BORDER_RADIUS": "10px",
    "COLORS": {
        "primary": {
            "50": "oklch(97.5% .012 165)", "100": "oklch(94% .03 165)", "200": "oklch(88% .055 165)",
            "300": "oklch(79% .08 165)", "400": "oklch(66% .1 165)", "500": "oklch(53% .095 165)",
            "600": "oklch(45% .09 165)", "700": "oklch(38% .075 165)", "800": "oklch(31% .06 165)",
            "900": "oklch(26% .05 165)", "950": "oklch(19% .04 165)",
        },
    },
    "DASHBOARD_CALLBACK": "config.admin_dashboard.dashboard_callback",
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Overview",
                "separator": False,
                "items": [
                    {"title": "Dashboard", "icon": "dashboard", "link": reverse_lazy("admin:index")},
                ],
            },
            {
                "title": "Accounts",
                "separator": True,
                "items": [
                    {"title": "Users", "icon": "person", "link": reverse_lazy("admin:accounts_user_changelist")},
                    _nav_item("Organizations", "business", "organization"),
                    _nav_item("Sender IDs", "badge", "senderid"),
                    _nav_item("API keys", "key", "apikey"),
                ],
            },
            {
                "title": "Messaging",
                "separator": True,
                "items": [
                    _nav_item("Messages", "sms", "message"),
                    _nav_item("OTP requests", "password", "otprequest"),
                    _nav_item("Customers", "groups", "customer"),
                    _nav_item("Templates", "article", "messagetemplate"),
                ],
            },
            {
                "title": "Billing",
                "separator": True,
                "items": [
                    _nav_item("Payments", "payments", "payment"),
                    _nav_item("Wallets", "account_balance_wallet", "wallet"),
                    _nav_item("Ledger", "receipt_long", "ledgerentry"),
                    _nav_item("SMS plans", "sell", "smsplan"),
                    _nav_item("Pricing tiers", "price_change", "pricingtier"),
                ],
            },
        ],
    },
}