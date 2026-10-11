"""Arkesel's delivery report (DLR) callback.

This is the missing half of sending: Arkesel's send API only confirms that a
message was *accepted* (that's what makes a Message "sent"). Whether it
actually reached the phone is reported later, asynchronously, as a callback
to this URL - and until this file existed, nothing in this app was listening
for it, so every message sat at "sent" forever even when it was genuinely
delivered a few seconds later.

Arkesel's exact callback field names aren't pinned down in their public docs
(their reference site is a JS app that doesn't expose its content to
automated fetching), so this view is deliberately tolerant: it accepts
either a JSON body or form/query parameters, matches several plausible key
spellings case-insensitively, and - most importantly - logs the full raw
payload on every call, matched or not. If the first real callback doesn't
update a message, the fix is to read that log line and adjust
_extract() below; nothing else about the design needs to change.

Setup (see README "Going live"):
    1. Set ARKESEL_DLR_SECRET (a long random value) and BACKEND_URL in .env.
    2. That's usually enough - providers.ArkeselProvider now sends
       callback_url on every request. Some Arkesel accounts instead require
       the callback URL to be registered once in the Arkesel dashboard
       (Settings -> SMS -> Delivery Callback, or similar); if delivery
       reports never seem to arrive, register the same URL there:
           https://YOUR-DOMAIN/api/webhooks/arkesel/<ARKESEL_DLR_SECRET>
"""
import hmac
import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DeliveryEvent, Message
from .services import fail_message

logger = logging.getLogger(__name__)

# Arkesel's own wording isn't publicly pinned down, so these match broadly
# (case-insensitive substring) rather than against one exact vocabulary.
# Order matters: FAILED patterns are checked first since "undelivered"
# contains "deliver" too.
_FAILED_HINTS = ("FAIL", "REJECT", "UNDELIV", "EXPIR", "DELET", "INVALID")
_DELIVERED_HINTS = ("DELIV", "SUCCESS")

# Plausible field-name spellings for each value we need, tried in order.
_ID_KEYS = ("id", "message_id", "messageid", "msgid", "sms_id", "reference", "ref")
_STATUS_KEYS = ("status", "delivery_status", "dlr_status", "dlrstatus", "dlr")
_NETWORK_KEYS = ("network", "network_name", "carrier")


def _lower_keys(data: dict) -> dict:
    return {str(k).lower(): v for k, v in data.items()}


def _first(data: dict, keys) -> str:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _normalize_status(raw: str) -> str | None:
    upper = raw.upper()
    if any(hint in upper for hint in _FAILED_HINTS):
        return Message.Status.FAILED
    if any(hint in upper for hint in _DELIVERED_HINTS):
        return Message.Status.DELIVERED
    return None  # an intermediate/unrecognised status - log it, change nothing


class ArkeselDeliveryWebhookView(APIView):
    """Arkesel calls this itself, so there's no session or API key: the
    secret path segment is the only proof it's really Arkesel. Accepts GET
    or POST since providers vary on which they use for callbacks."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []  # a 429 would just make Arkesel retry
    # Arkesel's exact content type for the callback isn't pinned down (see the
    # module docstring), so accept JSON, form-encoded, or multipart - whatever
    # shows up, instead of a blanket 415 like the site-wide JSON-only default.
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request, secret):
        return self._handle(request, secret, dict(request.query_params.items()))

    def post(self, request, secret):
        merged = dict(request.query_params.items())
        if isinstance(request.data, dict):
            # .update(request.data) would look like the obvious way to merge
            # this in, but request.data is a QueryDict for form/multipart
            # bodies, and dict.update() on a dict subclass copies its raw
            # internal storage (lists-of-values) instead of going through
            # QueryDict's own __getitem__/items() - so every value would
            # arrive here as e.g. ['DELIVERED'] instead of 'DELIVERED'.
            # Going through .items() uses QueryDict's real single-value
            # semantics regardless of which parser produced it.
            merged.update(request.data.items())
        return self._handle(request, secret, merged)

    def _handle(self, request, secret, raw: dict):
        if not settings.ARKESEL_DLR_SECRET or not hmac.compare_digest(secret, settings.ARKESEL_DLR_SECRET):
            # 404, not 401/403: don't confirm to an unauthenticated caller
            # that this path even means anything.
            return Response(status=status.HTTP_404_NOT_FOUND)

        data = _lower_keys(raw)
        provider_message_id = _first(data, _ID_KEYS)
        raw_status = _first(data, _STATUS_KEYS)
        network = _first(data, _NETWORK_KEYS)

        if not provider_message_id or not raw_status:
            logger.warning("Arkesel DLR callback missing id/status, raw payload: %r", raw)
            return Response(status=status.HTTP_200_OK)

        message = (
            Message.objects.filter(provider="arkesel", provider_message_id=provider_message_id)
            .order_by("-created_at")
            .first()
        )
        if message is None:
            logger.warning(
                "Arkesel DLR callback for unknown provider_message_id=%r status=%r raw=%r",
                provider_message_id, raw_status, raw,
            )
            return Response(status=status.HTTP_200_OK)

        DeliveryEvent.objects.create(message=message, status=raw_status[:20], payload=raw)

        normalized = _normalize_status(raw_status)
        if normalized == Message.Status.DELIVERED:
            updated = Message.objects.filter(
                pk=message.pk, status__in=[Message.Status.QUEUED, Message.Status.SENT]
            ).update(status=Message.Status.DELIVERED, delivered_at=timezone.now(), network=network or "")
            if not updated and network:
                Message.objects.filter(pk=message.pk, network="").update(network=network)
        elif normalized == Message.Status.FAILED:
            fail_message(message.pk, f"dlr_{raw_status.lower()[:40]}")
        else:
            logger.info(
                "Arkesel DLR for message %s: unrecognised status %r (stored as a DeliveryEvent, no status change)",
                message.pk, raw_status,
            )

        return Response(status=status.HTTP_200_OK)
