"""The things the assistant can look at or do, always for ONE organization.

The organization and user come from the logged-in session (ToolContext), never from
the model: no tool takes an organization, user or account id as input, so there is
nothing a confused or manipulated model could point at someone else's data.

Two tools have side effects: verify_topup (asks Paystack about the caller's own payment;
safe to repeat, never credits twice) and open_ticket. Everything else only reads.
"""
import datetime
import json
import logging
import re
import uuid
from dataclasses import dataclass

from django.db.models import Count, Sum
from django.utils import timezone

from common.errors import ApiError
from common.ratelimit import hit
from common.redis import get_redis
from common.spend import spend_key_for
from messaging import paystack
from messaging.models import Campaign, Message, Payment, SenderId, Wallet

from . import tickets
from .knowledge import explain_error

logger = logging.getLogger(__name__)

MAX_LIST = 10
MAX_RESULT_CHARS = 6000
PREVIEW_CHARS = 60


@dataclass
class ToolContext:
    org: object
    user: object
    conversation: object = None


def _clamp(limit, default=5) -> int:
    try:
        return max(1, min(int(limit), MAX_LIST))
    except (TypeError, ValueError):
        return default


def _iso(dt):
    return dt.isoformat(timespec="seconds") if dt else None


def _ghs(pesewas) -> str:
    return f"GHS {(pesewas or 0) / 100:,.2f}"


def _preview(message) -> str:
    """Message text is customer-written and can hold secrets (OTP codes) or instructions.
    Hide OTP bodies entirely and keep the rest short."""
    if message.category == Message.Category.OTP:
        return "(hidden: verification code)"
    text = " ".join(message.body.split())
    return text[:PREVIEW_CHARS] + ("..." if len(text) > PREVIEW_CHARS else "")


def _message_row(m) -> dict:
    return {
        "id": str(m.id), "to": m.recipient, "sender": m.sender, "status": m.status, "category": m.category or None,
        "cost": _ghs(m.cost_pesewas), "created": _iso(m.created_at), "error_code": m.error_code or None,
        "body_preview_untrusted": _preview(m),
    }


# ---------------------------------------------------------------------------
# Read-only
# ---------------------------------------------------------------------------
def get_account_overview(ctx, **_):
    org = ctx.org
    balance = Wallet.objects.filter(organization=org).values_list("balance_pesewas", flat=True).first() or 0
    spent = int(get_redis().get(spend_key_for(org.id)) or 0)
    senders = dict(SenderId.objects.filter(organization=org).values_list("status").annotate(n=Count("id")))
    since = timezone.now() - datetime.timedelta(days=7)
    week = dict(Message.objects.filter(organization=org, created_at__gte=since).values_list("status").annotate(n=Count("id")))
    return {
        "organization": org.name, "active": org.is_active,
        "wallet_balance": _ghs(balance),
        "daily_spend_limit": _ghs(org.daily_spend_cap_pesewas), "spent_today": _ghs(spent),
        "sender_ids_by_status": senders, "messages_last_7_days_by_status": week,
    }


def list_recent_messages(ctx, status=None, recipient=None, limit=5, **_):
    qs = Message.objects.filter(organization=ctx.org)
    if isinstance(status, str) and status in {s.value for s in Message.Status}:
        qs = qs.filter(status=status)
    digits = re.sub(r"\D", "", recipient if isinstance(recipient, str) else "")
    if len(digits) >= 4:
        qs = qs.filter(recipient__contains=digits[-9:])
    rows = [_message_row(m) for m in qs.order_by("-created_at")[:_clamp(limit)]]
    return {"count": len(rows), "messages": rows}


def get_message(ctx, message_id=None, **_):
    try:
        pk = uuid.UUID(str(message_id))
    except (ValueError, AttributeError, TypeError):
        return {"error": "That isn't a valid message id. Use list_recent_messages to find it."}
    m = Message.objects.filter(organization=ctx.org, pk=pk).first()
    if m is None:
        return {"error": "No message with that id on this account."}
    row = _message_row(m)
    row.update(
        segments=m.segments, network=m.network or None, sent_at=_iso(m.sent_at), delivered_at=_iso(m.delivered_at),
        error_meaning=explain_error(m.error_code),
        status_history=[{"status": e.status, "at": _iso(e.received_at)} for e in m.events.order_by("received_at")[:10]],
    )
    return row


def list_sender_ids(ctx, **_):
    rows = SenderId.objects.filter(organization=ctx.org).order_by("-created_at")[:MAX_LIST]
    return {"sender_ids": [
        {"name": s.name, "status": s.status, "rejection_reason_untrusted": s.rejection_reason or None,
         "submitted": _iso(s.submitted_at), "reviewed": _iso(s.reviewed_at)}
        for s in rows
    ]}


def list_payments(ctx, limit=5, **_):
    rows = Payment.objects.filter(organization=ctx.org).order_by("-created_at")[:_clamp(limit)]
    return {"payments": [
        {"reference": p.provider_reference, "amount": _ghs(p.amount_pesewas), "status": p.status,
         "plan": p.plan.name if p.plan_id else None, "created": _iso(p.created_at)}
        for p in rows
    ]}


def list_bulk_sends(ctx, limit=5, **_):
    rows = (Campaign.objects.filter(organization=ctx.org)
            .annotate(cost=Sum("messages__cost_pesewas")).order_by("-created_at")[:_clamp(limit)])
    return {"bulk_sends": [
        {"id": str(c.id), "status": c.status, "created": _iso(c.created_at), "numbers": c.total,
         "accepted": c.accepted, "skipped": c.skipped, "failed": c.failed,
         "skipped_reasons": {k: {"count": v, "meaning": explain_error(k)} for k, v in (c.skipped_reasons or {}).items()},
         "charged": _ghs(c.cost)}
        for c in rows
    ]}


# ---------------------------------------------------------------------------
# With side effects
# ---------------------------------------------------------------------------
def verify_topup(ctx, reference=None, **_):
    """Ask Paystack what happened to one of this account's own payments."""
    payment = Payment.objects.filter(
        organization=ctx.org, provider=paystack.PROVIDER, provider_reference=str(reference or "")
    ).first()
    if payment is None:
        return {"error": "No payment with that reference on this account. Use list_payments to see the references."}
    hit(f"rl:verifytopup:org:{ctx.org.id}", limit=10, window=3600, code="rate_limited",
        message="Payments have been re-checked a lot this hour.")
    before = payment.status
    payment = paystack.confirm_payment(payment)
    balance = Wallet.objects.filter(organization=ctx.org).values_list("balance_pesewas", flat=True).first() or 0
    return {"reference": payment.provider_reference, "status_before": before, "status_now": payment.status,
            "amount": _ghs(payment.amount_pesewas), "wallet_balance_now": _ghs(balance),
            "note": "pending after a check usually means the customer never finished paying on Paystack's page."}


def open_ticket(ctx, subject=None, details=None, **_):
    ticket = tickets.open_ticket(ctx.org, ctx.user, subject=subject, details=details, conversation=ctx.conversation)
    return {"ticket_number": ticket.pk, "status": ticket.status}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def _schema(properties=None, required=None):
    return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}


_LIMIT = {"type": "integer", "minimum": 1, "maximum": MAX_LIST, "description": "How many to return (default 5)."}

TOOLS = {
    "get_account_overview": (get_account_overview, "Wallet balance, daily spending limit and how much is spent today, "
        "sender ID counts by status, and message counts by status for the last 7 days.", _schema()),
    "list_recent_messages": (list_recent_messages, "Most recent messages on this account, newest first. Optionally filter "
        "by status or by (part of) the recipient's phone number.",
        _schema({"status": {"type": "string", "enum": [s.value for s in Message.Status]},
                 "recipient": {"type": "string", "description": "Phone number or its last digits."}, "limit": _LIMIT})),
    "get_message": (get_message, "Full detail of one message by id: status history, cost, and a plain-language meaning "
        "of any error code.", _schema({"message_id": {"type": "string"}}, ["message_id"])),
    "list_sender_ids": (list_sender_ids, "This account's sender ID requests with status and any rejection reason.", _schema()),
    "list_payments": (list_payments, "Recent wallet top-up payments with reference and status.", _schema({"limit": _LIMIT})),
    "verify_topup": (verify_topup, "Ask Paystack whether one of this account's top-up payments went through, and credit "
        "the wallet if it did (never twice). Use when a customer says they paid but the balance didn't change.",
        _schema({"reference": {"type": "string", "description": "A payment reference from list_payments."}}, ["reference"])),
    "list_bulk_sends": (list_bulk_sends, "Recent bulk SMS sends with how many numbers were sent, skipped (and why) or failed.",
        _schema({"limit": _LIMIT})),
    "open_ticket": (open_ticket, "Hand the problem to our staff. Write a clear subject and details that include what you "
        "found, so nobody has to ask the customer again. Allowed at most twice per chat.",
        _schema({"subject": {"type": "string", "maxLength": tickets.MAX_SUBJECT},
                 "details": {"type": "string", "maxLength": tickets.MAX_DETAILS}}, ["subject", "details"])),
}

TOOL_DEFINITIONS = [{"name": n, "description": d, "input_schema": s} for n, (_f, d, s) in TOOLS.items()]


def run_tool(ctx: ToolContext, name: str, arguments) -> tuple[str, bool]:
    """Run one tool call. Returns (text for the model, is_error). Never raises."""
    entry = TOOLS.get(name)
    if entry is None:
        return json.dumps({"error": f"There is no tool called {name}."}), True
    args = arguments if isinstance(arguments, dict) else {}
    try:
        result = entry[0](ctx, **{k: v for k, v in args.items() if k in entry[2]["properties"]})
    except ApiError as exc:
        return json.dumps({"error": exc.message}), True
    except Exception:
        logger.exception("Support tool %s failed", name)
        return json.dumps({"error": "That lookup failed. Offer to open a ticket instead."}), True
    text = json.dumps(result, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "...(cut short)"
    return text, "error" in result
