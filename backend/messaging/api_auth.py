"""
Bearer API-key authentication for the public API.

Keys look like  sk_live_<random>  /  sk_test_<random>.
Only a SHA-256 hash is stored; the raw key is shown once at creation.
(SHA-256 is fine here because keys are long random strings, not passwords.)
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from common.ratelimit import client_ip, hit

from .models import ApiKey, Organization

PREFIX_LEN = 16


def create_api_key(org: Organization, name: str, *, live: bool) -> tuple[ApiKey, str]:
    """Returns (ApiKey row, raw key). Show the raw key to the user once."""
    raw = f"sk_{'live' if live else 'test'}_{secrets.token_urlsafe(32)}"
    key = ApiKey.objects.create(
        organization=org,
        name=name,
        prefix=raw[:PREFIX_LEN],
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        is_live=live,
    )
    return key, raw


class ApiPrincipal:
    """Minimal 'user' so DRF's IsAuthenticated and throttles work for API-key callers."""
    is_authenticated = True
    is_anonymous = False

    def __init__(self, organization: Organization):
        self.organization = organization
        self.pk = organization.pk


class ApiKeyAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        raw = header[7:].strip()

        key = self._lookup(raw)
        if key is None:
            # Keys are 256-bit random, so guessing is hopeless, but cap failures anyway
            # (this runs before DRF's throttles, which only see authenticated requests).
            hit(f"rl:apikey_fail:{client_ip(request)}", limit=30, window=300,
                code="too_many_auth_failures", message="Too many failed authentication attempts.")
            raise AuthenticationFailed("Invalid API key.", code="invalid_api_key")

        if not key.organization.is_active:
            raise AuthenticationFailed("This account is suspended.", code="account_suspended")
        if key.allowed_ips and request.META.get("REMOTE_ADDR") not in key.allowed_ips:
            # Behind a proxy, resolve the real client IP (see common.ratelimit.client_ip).
            raise AuthenticationFailed("This IP address isn't allowed for this key.", code="ip_not_allowed")
        self._touch(key)
        return ApiPrincipal(key.organization), key

    @staticmethod
    def _lookup(raw: str):
        if len(raw) <= PREFIX_LEN:
            return None
        digest = hashlib.sha256(raw.encode()).hexdigest()
        candidates = ApiKey.objects.select_related("organization").filter(
            prefix=raw[:PREFIX_LEN], revoked_at__isnull=True
        )
        for key in candidates:
            if hmac.compare_digest(key.key_hash, digest):
                return key
        return None

    @staticmethod
    def _touch(key: ApiKey):
        # Avoid a DB write on every request.
        now = timezone.now()
        if key.last_used_at is None or now - key.last_used_at > timedelta(minutes=1):
            ApiKey.objects.filter(pk=key.pk).update(last_used_at=now)
