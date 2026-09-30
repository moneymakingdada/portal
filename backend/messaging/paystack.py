"""
Wallet top-ups through Paystack's hosted checkout.

The flow:
  1. start_topup()      creates a pending Payment, asks Paystack for a checkout
                        URL, and returns it. The browser is sent there to pay.
  2. Paystack           takes the payment, then does two things at once:
       - redirects the browser back to FRONTEND_URL/dashboard/wallet?reference=...
       - POSTs a `charge.success` webhook to /api/webhooks/paystack
  3. confirm_payment()  (from the redirect) and handle_webhook() (from the
                        webhook) both end up in apply_result(), which credits
                        the wallet exactly once no matter which arrives first,
                        or whether both do.

Money is only ever credited when Paystack itself says the charge succeeded
with the exact amount and currency we asked for.
"""
import hashlib
import hmac
import logging
import uuid

import requests
from django.conf import settings
from django.db import transaction

from common.errors import ApiError

from .ledger import credit_topup
from .models import Payment

logger = logging.getLogger(__name__)

PROVIDER = "paystack"
CURRENCY = "GHS"
TIMEOUT = (3.05, 10)

# Paystack transaction statuses that mean "this attempt is over and failed".
# Anything else that isn't "success" (abandoned, ongoing, pending, ...) may
# still complete, so the Payment stays pending.
_FAILED_STATUSES = {"failed", "reversed"}


def is_configured() -> bool:
    return bool(settings.PAYSTACK_SECRET_KEY)


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}


def _require_configured():
    if not is_configured():
        raise ApiError("payments_not_configured", "Online payments aren't set up yet.", 503)


# ---------------------------------------------------------------------------
# 1. Start a payment
# ---------------------------------------------------------------------------
def start_topup(*, org, email: str, amount_pesewas: int, plan=None) -> dict:
    """Create a pending Payment and return {authorization_url, reference}."""
    _require_configured()
    reference = f"portal_{uuid.uuid4().hex}"
    payment = Payment.objects.create(
        organization=org, provider=PROVIDER, provider_reference=reference,
        amount_pesewas=amount_pesewas, plan=plan,
    )
    payload = {
        "email": email,
        "amount": amount_pesewas,            # Paystack takes the smallest unit: pesewas for GHS
        "currency": CURRENCY,
        "reference": reference,
        "callback_url": f"{settings.FRONTEND_URL}/dashboard/wallet",
        "metadata": {"organization_id": str(org.id), "plan_id": plan.id if plan else None},
    }
    try:
        response = requests.post(
            f"{settings.PAYSTACK_API_URL}/transaction/initialize", json=payload, headers=_headers(), timeout=TIMEOUT
        )
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Paystack initialize failed for %s: %s", reference, exc)
        _mark_failed(payment, {"error": str(exc)})
        raise ApiError("payment_unavailable", "We couldn't reach the payment provider. Try again shortly.", 502) from exc

    url = (body.get("data") or {}).get("authorization_url") if isinstance(body, dict) else None
    if not response.ok or not body.get("status") or not url:
        logger.error("Paystack rejected initialize for %s: %s", reference, body)
        _mark_failed(payment, body if isinstance(body, dict) else {"body": str(body)[:500]})
        raise ApiError("payment_unavailable", "We couldn't start that payment. Try again shortly.", 502)
    return {"authorization_url": url, "reference": reference}


def _mark_failed(payment: Payment, raw: dict) -> None:
    Payment.objects.filter(pk=payment.pk).exclude(status=Payment.Status.SUCCESS).update(
        status=Payment.Status.FAILED, raw_response=raw
    )


# ---------------------------------------------------------------------------
# 2a. The customer came back from checkout
# ---------------------------------------------------------------------------
def confirm_payment(payment: Payment) -> Payment:
    """Ask Paystack what happened to this payment and act on the answer.
    Safe to call repeatedly; never credits twice."""
    if payment.status == Payment.Status.SUCCESS:
        return payment
    _require_configured()
    try:
        response = requests.get(
            f"{settings.PAYSTACK_API_URL}/transaction/verify/{payment.provider_reference}",
            headers=_headers(), timeout=TIMEOUT,
        )
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Paystack verify failed for %s: %s", payment.provider_reference, exc)
        raise ApiError("payment_unavailable", "We couldn't check that payment yet. Try again shortly.", 502) from exc

    if response.status_code == 404:
        # Paystack has no record: the customer never reached checkout.
        return payment
    if not response.ok or not isinstance(body, dict) or not body.get("status"):
        logger.error("Paystack verify error for %s: %s", payment.provider_reference, body)
        raise ApiError("payment_unavailable", "We couldn't check that payment yet. Try again shortly.", 502)
    return apply_result(payment.pk, body.get("data") or {}, raw=body)


# ---------------------------------------------------------------------------
# 2b. Paystack told us directly
# ---------------------------------------------------------------------------
def verify_signature(raw_body: bytes, signature: str) -> bool:
    """Paystack signs each webhook body with HMAC-SHA512 using the secret key."""
    if not settings.PAYSTACK_SECRET_KEY or not signature:
        return False   # an empty key would let anyone compute a valid signature
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())


def handle_webhook(event: dict) -> None:
    """Act on an already signature-verified webhook event."""
    if event.get("event") != "charge.success":
        return
    data = event.get("data") or {}
    reference = data.get("reference")
    payment = Payment.objects.filter(provider=PROVIDER, provider_reference=reference).first() if reference else None
    if payment is None:
        # One Paystack account can serve several apps; events for payments that
        # didn't start here are expected and not ours to act on.
        logger.info("Ignoring Paystack event for unknown reference %r", reference)
        return
    apply_result(payment.pk, data, raw=event)


# ---------------------------------------------------------------------------
# Shared by both paths
# ---------------------------------------------------------------------------
def apply_result(payment_id, tx: dict, *, raw: dict) -> Payment:
    """Credit the wallet if `tx` (Paystack's description of the charge) is a
    successful payment of exactly what this Payment asked for."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        if payment.status == Payment.Status.SUCCESS:
            return payment   # already credited: a duplicate webhook, or both paths arrived

        status = tx.get("status")
        if status == "success":
            if _amount_matches(tx, payment):
                payment.status = Payment.Status.SUCCESS
                payment.raw_response = raw
                payment.save(update_fields=["status", "raw_response"])
                credit_topup(payment)
                return payment
            logger.error(
                "Paystack payment %s succeeded but didn't match: expected %s %s, got %s %s",
                payment.provider_reference, payment.amount_pesewas, CURRENCY, tx.get("amount"), tx.get("currency"),
            )
            payment.status = Payment.Status.FAILED
        elif status in _FAILED_STATUSES:
            payment.status = Payment.Status.FAILED
        else:
            return payment   # still in progress on Paystack's side: leave it pending
        payment.raw_response = raw
        payment.save(update_fields=["status", "raw_response"])
        return payment


def _amount_matches(tx: dict, payment: Payment) -> bool:
    try:
        amount = int(tx.get("amount"))
    except (TypeError, ValueError):
        return False
    return amount == payment.amount_pesewas and tx.get("currency") == CURRENCY
