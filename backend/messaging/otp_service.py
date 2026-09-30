"""
OTP business logic for the public API (/api/v1/otp/*).

Redis layout:
    otp:{request_id}            code state (see common/codes.py), TTL = code lifetime
    otp:cd:{org}:{phone}        resend cooldown flag, TTL = RESEND_COOLDOWN
    rl:otp:*                    fixed-window rate-limit counters
    spend:{org}:{YYYYMMDD}      per-organization daily spend counter (pesewas)
"""
import logging
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from common.codes import CodeCheck, check_code, generate_code, hash_code, store_code
from common.errors import ApiError
from common.phone import InvalidPhone, normalize_gh_number
from common.ratelimit import hit
from common.redis import get_redis
from common.spend import check_daily_cap, record_spend

from .ledger import InsufficientFunds, debit_message
from .models import Message, OtpRequest
from .pricing import count_segments, price_for_segments, resolve_sender
from .services import fail_message

logger = logging.getLogger(__name__)

RESEND_COOLDOWN = 60  # seconds
MAX_ATTEMPTS = 3
DEFAULT_TEMPLATE = "Your verification code is {code}. It expires soon. Never share it."


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------
def send_otp(*, org, api_key, to, purpose="", length=6, ttl=300,
             sender_id=None, template=None, client_ip=None) -> dict:
    r = get_redis()
    try:
        phone = normalize_gh_number(to)
    except InvalidPhone as exc:
        raise ApiError("invalid_phone", str(exc)) from exc
    sender = resolve_sender(org, sender_id)

    # --- abuse controls (SMS pumping is the main cost risk) -----------------
    hit(f"rl:otp:phone:{org.id}:{phone}", limit=5, window=3600, code="phone_rate_limited",
        message="Too many codes requested for this number. Try again later.")
    hit(f"rl:otp:org:{org.id}", limit=600, window=60, code="org_rate_limited",
        message="Too many requests. Slow down.")
    if client_ip:  # the END USER's IP, passed by the customer's backend
        hit(f"rl:otp:ip:{org.id}:{client_ip}", limit=30, window=3600, code="ip_rate_limited",
            message="Too many codes requested from this address. Try again later.")

    cooldown_key = f"otp:cd:{org.id}:{phone}"
    if not r.set(cooldown_key, 1, ex=RESEND_COOLDOWN, nx=True):
        raise ApiError("cooldown", "Wait before requesting another code for this number.",
                       429, retry_after=max(int(r.ttl(cooldown_key)), 1))

    # --- build the message --------------------------------------------------
    is_live = api_key.is_live
    # Test keys use a fixed code and never send an SMS.
    code = generate_code(length) if is_live else "1234567890"[:length]
    request_id = uuid.uuid4()
    template = template or DEFAULT_TEMPLATE
    body = template.replace("{code}", code)
    masked_body = template.replace("{code}", "*" * length)   # what we persist
    segments = count_segments(body)
    cost = price_for_segments(segments) if is_live else 0

    spend_key = None
    if is_live:
        try:
            spend_key = check_daily_cap(r, org, cost)
        except ApiError:
            r.delete(cooldown_key)
            raise

    expires_at = timezone.now() + timedelta(seconds=ttl)
    redis_key = f"otp:{request_id}"
    code_hash = hash_code(request_id, code)

    try:
        with transaction.atomic():
            message = None
            if is_live:
                message = Message.objects.create(
                    organization=org, api_key=api_key, channel=Message.Channel.SMS,
                    category=Message.Category.OTP, sender=sender, recipient=phone,
                    body=masked_body, segments=segments, cost_pesewas=cost,
                )
                debit_message(message)          # raises InsufficientFunds

            OtpRequest.objects.create(
                id=request_id, organization=org, recipient=phone, purpose=purpose,
                code_hash=code_hash, code_length=length, max_attempts=MAX_ATTEMPTS,
                message=message, client_ip=client_ip or None, expires_at=expires_at,
            )

            # The Redis write is the last step inside the transaction: if it
            # fails, the debit rolls back. If the commit itself fails afterwards,
            # the orphan key is harmless (nobody has its request_id).
            store_code(r, redis_key, scope=str(org.id), code_hash=code_hash, ttl=ttl,
                       max_attempts=MAX_ATTEMPTS)

            if is_live:
                transaction.on_commit(
                    lambda: _dispatch(r, redis_key, cooldown_key, spend_key, cost, message.id, body)
                )
    except InsufficientFunds:
        r.delete(cooldown_key, redis_key)
        raise ApiError("insufficient_funds", "Wallet balance is too low to send this message.", 402)
    except Exception:
        r.delete(cooldown_key, redis_key)
        raise

    return {"request_id": str(request_id), "expires_at": expires_at, "to": phone}


def _dispatch(r, redis_key, cooldown_key, spend_key, cost, message_id, plaintext_body):
    """Runs after the transaction commits. The plaintext code only exists in this
    task's arguments (a short-lived broker message); the database keeps the masked body."""
    try:
        from .tasks import send_sms
        send_sms.delay(str(message_id), plaintext_body)
    except Exception as exc:
        logger.exception("Could not enqueue SMS for message %s", message_id)
        fail_message(message_id, "queue_unavailable")   # refunds the debit
        r.delete(redis_key, cooldown_key)
        raise ApiError("sms_unavailable", "We couldn't queue the message. Try again shortly.", 503) from exc
    record_spend(r, spend_key, cost)


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
def verify_otp(*, org, request_id, code: str) -> dict:
    r = get_redis()
    status, attempts_left = check_code(
        r, f"otp:{request_id}", scope=str(org.id), code_hash=hash_code(request_id, code)
    )
    pending = OtpRequest.objects.filter(
        id=request_id, organization=org, status=OtpRequest.Status.PENDING
    )

    if status is CodeCheck.NOT_FOUND:
        # Same error for "never existed", "expired", "already used" and "someone else's".
        raise ApiError("invalid_or_expired", "Code is invalid or has expired.")
    if status is CodeCheck.VERIFIED:
        pending.update(status=OtpRequest.Status.VERIFIED, verified_at=timezone.now())
        # TODO: fire the customer's `otp.verified` webhook
        return {"verified": True}
    if status is CodeCheck.LOCKED:
        pending.update(status=OtpRequest.Status.LOCKED)
        raise ApiError("too_many_attempts", "Too many attempts. Request a new code.", 429)
    if status is CodeCheck.WRONG_LOCKED:
        pending.update(status=OtpRequest.Status.LOCKED)
        return {"verified": False, "attempts_left": 0}
    return {"verified": False, "attempts_left": attempts_left}
