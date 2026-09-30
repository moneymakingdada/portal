"""Shared helpers for the test suite (imported only from tests)."""
from django.conf import settings
from django.core.cache import cache
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from common.redis import get_redis


def reset_state():
    from messaging.providers import MemoryProvider

    # The tests flush Redis, so refuse to run against anything but the test database.
    assert settings.REDIS_URL.endswith("/15"), "Tests must use Redis database 15 (see config/settings_test.py)"
    get_redis().flushdb()
    cache.clear()
    MemoryProvider.reset()


class RedisAPITestCase(APITestCase):
    def setUp(self):
        super().setUp()
        reset_state()


class RedisAPITransactionTestCase(APITransactionTestCase):
    def setUp(self):
        super().setUp()
        reset_state()


def make_account(email="owner@example.com", org_name="Acme Ltd", balance=0, live_key=True):
    """A user + organization (+ wallet) with an API key. Returns (user, org, api_key, raw_key)."""
    from accounts.models import User
    from messaging.api_auth import create_api_key
    from messaging.ledger import post_entry
    from messaging.models import LedgerEntry, Organization

    user = User.objects.create_user(email, password="Correct-horse-9", full_name="Test Owner")
    org = Organization.objects.create(name=org_name, owner=user)
    if balance:
        post_entry(organization_id=org.id, kind=LedgerEntry.Kind.TOPUP, amount_pesewas=balance,
                   idempotency_key=f"test-topup:{org.id}")
    key, raw = create_api_key(org, "test key", live=live_key)
    return user, org, key, raw


def api_client(raw_key: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")
    return client
