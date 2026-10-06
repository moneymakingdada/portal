"""Generic bulk SMS: send the same message to one or many numbers, with no
customer or template semantics. For that, see messaging/customers.py instead -
this is the raw primitive behind "receipts, alerts, reminders to anyone"."""
import logging

from django.conf import settings
from django.db import transaction

from common.errors import ApiError
from common.phone import InvalidPhone, normalize_gh_number
from common.ratelimit import hit
from common.redis import get_redis
from common.spend import check_daily_cap, record_spend

from .ledger import InsufficientFunds, debit_message
from .models import Message
from .pricing import count_segments, price_for_segments, resolve_sender

logger = logging.getLogger(__name__)


def send_bulk_sms(*, org, api_key, recipients: list[str], message: str, sender_id=None) -> list[dict]:
    """Normalizes and validates every recipient before sending any message, so
    one bad number in a batch can't result in a half-charged, half-sent call.
    Returns one result dict per recipient, in the order given."""
    if not recipients:
        raise ApiError("missing_recipients", "Provide at least one recipient in `to`.")
    if len(recipients) > settings.BULK_SMS_MAX_RECIPIENTS:
        raise ApiError(
            "too_many_recipients",
            f"Send to at most {settings.BULK_SMS_MAX_RECIPIENTS} recipients per call.",
        )

    normalized = []
    invalid = []
    for raw in recipients:
        try:
            normalized.append(normalize_gh_number(raw))
        except InvalidPhone:
            invalid.append(raw)
    if invalid:
        raise ApiError("invalid_phone", "One or more recipients aren't valid Ghana numbers.", invalid=invalid)

    sender = resolve_sender(org, sender_id)
    r = get_redis()
    hit(f"rl:sms:org:{org.id}", limit=300, window=60, code="org_rate_limited",
        message="Too many messages sent in a short time. Slow down.")

    is_live = api_key.is_live
    segments = count_segments(message)
    cost_each = price_for_segments(segments) if is_live else 0
    total_cost = cost_each * len(normalized)

    spend_key = None
    if is_live and total_cost > 0:
        spend_key = check_daily_cap(r, org, total_cost)

    results = []
    created_ids = []
    try:
        with transaction.atomic():
            for phone in normalized:
                msg = Message.objects.create(
                    organization=org, api_key=api_key, channel=Message.Channel.SMS,
                    category=Message.Category.SMS, sender=sender, recipient=phone,
                    body=message, segments=segments, cost_pesewas=cost_each if is_live else 0,
                )
                if is_live:
                    debit_message(msg)   # raises InsufficientFunds - rolls back the whole batch
                created_ids.append(msg.id)
                results.append({"message_id": str(msg.id), "to": phone, "status": "queued" if is_live else "test"})

            if is_live:
                transaction.on_commit(lambda: _dispatch(created_ids, message, spend_key, total_cost))
    except InsufficientFunds:
        raise ApiError("insufficient_funds", "Wallet balance is too low to send this batch.", 402)

    return results


def _dispatch(message_ids: list, body: str, spend_key, total_cost: int) -> None:
    from .tasks import send_sms
    for message_id in message_ids:
        send_sms.delay(str(message_id), body)
    if spend_key:
        record_spend(get_redis(), spend_key, total_cost)