"""SMS provider adapters.

To add a provider: subclass BaseProvider, implement send(), and register it in
_PROVIDERS. send() returns a ProviderResult for definite outcomes and raises
ProviderTransientError when a retry might succeed (network error, HTTP 5xx).
"""
import logging
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from common.errors import ApiError

logger = logging.getLogger(__name__)


class ProviderTransientError(Exception):
    """The provider couldn't be reached or had a server-side problem. Safe to retry."""


@dataclass
class ProviderResult:
    ok: bool
    status: str = "sent"          # "sent" = accepted by the provider, "delivered" = confirmed
    provider_message_id: str = ""
    error_code: str = ""
    error_message: str = ""


class BaseProvider:
    name = "base"

    def send(self, *, sender: str, recipient: str, body: str) -> ProviderResult:
        raise NotImplementedError


class ConsoleProvider(BaseProvider):
    """Development only: prints the message instead of sending it."""
    name = "console"

    def send(self, *, sender, recipient, body):
        logger.warning("[SMS console backend] from=%s to=%s message=%r", sender, recipient, body)
        return ProviderResult(ok=True, status="delivered", provider_message_id="console")


class MemoryProvider(BaseProvider):
    """Test double: records messages in `outbox`. `behavior` can be "ok", "reject" or "transient"."""
    name = "memory"
    outbox: list = []
    behavior = "ok"

    @classmethod
    def reset(cls):
        cls.outbox = []
        cls.behavior = "ok"

    def send(self, *, sender, recipient, body):
        if MemoryProvider.behavior == "transient":
            raise ProviderTransientError("simulated outage")
        if MemoryProvider.behavior == "reject":
            return ProviderResult(ok=False, error_code="provider_rejected", error_message="simulated rejection")
        MemoryProvider.outbox.append({"sender": sender, "recipient": recipient, "body": body})
        return ProviderResult(ok=True, status="delivered", provider_message_id=f"mem-{len(MemoryProvider.outbox)}")


class ArkeselProvider(BaseProvider):
    """Arkesel SMS API v2: POST {sender, message, recipients[]} with an `api-key` header."""
    name = "arkesel"

    def send(self, *, sender, recipient, body):
        api_key = settings.ARKESEL_API_KEY
        if not api_key:
            return ProviderResult(ok=False, error_code="provider_not_configured",
                                  error_message="ARKESEL_API_KEY is not set")
        payload = {
            "sender": sender,
            "message": body,
            "recipients": [recipient.lstrip("+")],   # Arkesel wants 233XXXXXXXXX
        }
        if settings.ARKESEL_SANDBOX:
            payload["sandbox"] = True
        try:
            response = requests.post(
                settings.ARKESEL_SMS_URL, json=payload, headers={"api-key": api_key}, timeout=(3.05, 10)
            )
        except requests.RequestException as exc:
            raise ProviderTransientError(str(exc)) from exc
        if response.status_code >= 500:
            raise ProviderTransientError(f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.ok and isinstance(data, dict) and data.get("status") == "success":
            items = data.get("data") or []
            first = items[0] if items and isinstance(items[0], dict) else {}
            return ProviderResult(ok=True, status="sent", provider_message_id=str(first.get("id", "")))
        message = data.get("message") if isinstance(data, dict) else None
        return ProviderResult(ok=False, error_code="provider_rejected",
                              error_message=str(message or response.text)[:200])


_PROVIDERS = {
    "console": ConsoleProvider,
    "memory": MemoryProvider,
    "arkesel": ArkeselProvider,
}


def get_provider() -> BaseProvider:
    try:
        return _PROVIDERS[settings.SMS_BACKEND]()
    except KeyError:
        raise ImproperlyConfigured(
            f"Unknown SMS_BACKEND {settings.SMS_BACKEND!r}. Choose one of: {', '.join(_PROVIDERS)}."
        ) from None


def send_platform_sms(recipient: str, body: str) -> None:
    """Send a message from the platform itself (e.g. a sign-up code).

    Synchronous and not billed to any wallet. Raises ApiError(502) if it can't be sent.
    """
    provider = get_provider()
    try:
        result = provider.send(sender=settings.DEFAULT_SENDER_ID, recipient=recipient, body=body)
    except ProviderTransientError as exc:
        logger.warning("Platform SMS to %s failed (transient): %s", recipient, exc)
        raise ApiError("sms_failed", "We couldn't send the code. Try again in a moment.", 502) from exc
    if not result.ok:
        logger.error("Platform SMS to %s rejected: %s %s", recipient, result.error_code, result.error_message)
        raise ApiError("sms_failed", "We couldn't send the code. Try again in a moment.", 502)
