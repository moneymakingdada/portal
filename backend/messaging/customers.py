"""
Customer messaging: an organization's own customers, and the thank-you,
birthday, holiday, welcome and custom messages it sends them. This is about
building a relationship with someone the organization has already done (or
is about to do) business with - unlike OTP, which only verifies a phone
number belongs to whoever is using it right now.

Redis layout:
    rl:custmsg:org:{org}      per-organization send-rate limit
    spend:{org}:{YYYYMMDD}    shared with OTP (see common/spend.py)
"""
import logging

from django.db import transaction
from django.utils import timezone

from common.errors import ApiError
from common.phone import InvalidPhone, normalize_gh_number
from common.ratelimit import hit
from common.redis import get_redis
from common.spend import check_daily_cap, record_spend

from .ledger import InsufficientFunds, debit_message
from .models import Customer, Message
from .pricing import count_segments, price_for_segments, resolve_sender
from .services import fail_message
from .templates import placeholder_context, render_template, resolve_body

logger = logging.getLogger(__name__)


def upsert_customer(org, *, phone: str, name: str = "", email: str = "", birthday=None) -> Customer:
    """Create or update a customer by (organization, phone). Blank fields on
    the call never erase a value the customer already has on file."""
    try:
        normalized = normalize_gh_number(phone)
    except InvalidPhone as exc:
        raise ApiError("invalid_phone", str(exc)) from exc

    customer, _ = Customer.objects.get_or_create(organization=org, phone=normalized)
    changed = []
    if name and name != customer.name:
        customer.name, changed = name, changed + ["name"]
    if email and email != customer.email:
        customer.email, changed = email, changed + ["email"]
    if birthday and birthday != customer.birthday:
        customer.birthday, changed = birthday, changed + ["birthday"]
    if changed:
        customer.save(update_fields=changed + ["updated_at"])
    return customer


def send_customer_message(*, org, api_key=None, to=None, customer=None, category=None, template_id=None,
                           message=None, customer_name=None, amount_pesewas=None,
                           sender_id=None, save_customer=True, idempotency_key="") -> dict:
    """Send a thank-you, birthday, holiday, welcome or custom message to a
    phone number, optionally attaching it to (and creating) a Customer.

    Pass either `to` (a phone number; a Customer is looked up or created by
    phone when `save_customer` is true) or an existing `customer` instance
    directly - the birthday task already has one in hand and shouldn't create
    a duplicate or bump its updated_at.

    Exactly one of `template_id`, `category`, or `message` chooses the text:
    - template_id: use this saved template's body (and its category)
    - category alone: use the org's default template for that category, or
      the built-in suggestion if the org hasn't saved one
    - message: custom text, sent as-is (still supports {customer_name} /
      {business_name} / {amount} placeholders)
    """
    r = get_redis()
    if customer is not None:
        phone = customer.phone
    elif to:
        try:
            phone = normalize_gh_number(to)
        except InvalidPhone as exc:
            raise ApiError("invalid_phone", str(exc)) from exc
    else:
        raise ApiError("missing_recipient", "Provide a recipient phone number.")
    if not (template_id or category or message):
        raise ApiError("missing_content", "Provide a template_id, a category, or a message.")

    sender = resolve_sender(org, sender_id)

    # A steady per-organization limit bounds the damage from a runaway
    # integration loop; a legitimate business sending to many customers in a
    # short burst is expected and not otherwise restricted here.
    hit(f"rl:custmsg:org:{org.id}", limit=300, window=60, code="org_rate_limited",
        message="Too many messages sent in a short time. Slow down.")

    template = None
    if message:
        body_template, resolved_category = message, (category or "custom")
    else:
        body_template, template, resolved_category = resolve_body(
            org=org, category=category, template_id=template_id
        )

    if customer is None and save_customer:
        customer = upsert_customer(org, phone=phone, name=customer_name or "")

    context = placeholder_context(
        customer=customer, business_name=org.name, customer_name=customer_name, amount_pesewas=amount_pesewas
    )
    body = render_template(body_template, context)
    segments = count_segments(body)
    cost = price_for_segments(segments)
    is_live = api_key.is_live if api_key else True

    spend_key = None
    if is_live:
        spend_key = check_daily_cap(r, org, cost)

    try:
        with transaction.atomic():
            defaults = dict(
                api_key=api_key, channel=Message.Channel.SMS, category=resolved_category,
                customer=customer, template=template, sender=sender, recipient=phone,
                body=body, segments=segments, cost_pesewas=cost if is_live else 0,
            )
            if idempotency_key:
                msg, created = Message.objects.get_or_create(
                    organization=org, idempotency_key=idempotency_key, defaults=defaults
                )
                if not created:
                    return {"message_id": str(msg.id), "to": msg.recipient, "body": msg.body,
                            "customer_id": str(msg.customer_id) if msg.customer_id else None}
            else:
                msg = Message.objects.create(organization=org, idempotency_key=idempotency_key, **defaults)

            if is_live:
                debit_message(msg)  # raises InsufficientFunds
                transaction.on_commit(lambda: _dispatch(spend_key, cost, msg.id, body))
    except InsufficientFunds:
        raise ApiError("insufficient_funds", "Wallet balance is too low to send this message.", 402)

    return {
        "message_id": str(msg.id), "to": phone, "body": body,
        "customer_id": str(customer.id) if customer else None,
    }


def _dispatch(spend_key, cost, message_id, body):
    try:
        from .tasks import send_sms
        send_sms.delay(str(message_id), body)
    except Exception:
        logger.exception("Could not enqueue customer message %s", message_id)
        fail_message(message_id, "queue_unavailable")  # refunds the debit
        return
    if spend_key:
        r = get_redis()
        record_spend(r, spend_key, cost)


# ---------------------------------------------------------------------------
# Birthday automation - a daily Celery beat task (see config/settings.py and
# messaging/tasks.py) calls send_birthday_messages() once a day.
# ---------------------------------------------------------------------------
def send_birthday_messages(*, today=None) -> dict:
    """Send each opted-in organization's birthday message to every customer
    whose birthday (month and day; the year on file is ignored) is today.
    Safe to run more than once on the same day: each send is keyed so it can
    only happen once per (customer, date).
    """
    today = today or timezone.localdate()
    sent, skipped, failed = 0, 0, 0

    customers = (
        Customer.objects.filter(
            birthday__month=today.month, birthday__day=today.day,
            organization__birthday_messages_enabled=True, organization__is_active=True,
        )
        .select_related("organization")
    )
    for customer in customers:
        org = customer.organization
        idempotency_key = f"birthday:{customer.id}:{today.isoformat()}"
        try:
            send_customer_message(
                org=org, customer=customer, category=Message.Category.BIRTHDAY,
                customer_name=customer.name, idempotency_key=idempotency_key,
            )
            sent += 1
        except ApiError as exc:
            # Insufficient funds / daily cap / rate limit: skip this one and
            # keep going, rather than letting one organization's problem stop
            # everyone else's birthday messages.
            logger.info("Skipped birthday message for customer %s: %s", customer.id, exc.code)
            skipped += 1
        except Exception:
            logger.exception("Birthday message failed for customer %s", customer.id)
            failed += 1

    return {"date": today.isoformat(), "sent": sent, "skipped": skipped, "failed": failed}
