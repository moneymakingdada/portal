"""Settings for the test suite:  python manage.py test --settings=config.settings_test

Uses a dedicated Redis database (15) that the tests flush freely, so never point
REDIS_URL at a database you care about.
"""
import os

os.environ.setdefault("DJANGO_DEBUG", "True")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
os.environ.setdefault("OTP_HMAC_KEY", "test-otp-hmac-key")
os.environ["SMS_BACKEND"] = "memory"

from .settings import *  # noqa: E402,F401,F403

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
CELERY_BROKER_URL = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast tests only
SIGNUP_BONUS_PESEWAS = 50
DEFAULT_PRICE_PER_SEGMENT_PESEWAS = 5
LOGGING["root"]["level"] = "WARNING"  # noqa: F405
LOGGING["loggers"] = {"django.request": {"level": "ERROR"}}  # noqa: F405  (expected 4xx responses are noisy)
