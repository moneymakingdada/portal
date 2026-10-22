"""
Bulk sending: the same message to many numbers.

  review()          what *would* happen (counts, cost, a sample) - changes nothing
  create_campaign() checks the money, records the batch, queues the background run
  run_campaign()    sends to each number through send_customer_message(), the same
                    path a single message takes, so opt-outs, the daily spend cap,
                    pricing, wallet debits and refunds all behave identically

A bulk send is slower than one request should be, so it always runs in the
background (Celery) and the browser polls its progress.

Safe to run twice: every message carries the key bulk:{campaign}:{phone}, so a
re-run (a crashed or re-queued worker) replays what was already sent instead of
charging again.
"""
import datetime
import logging

from celery.exceptions import SoftTimeLimitExceeded
from django.db import IntegrityError, transaction
from django.utils import timezone

from common.errors import ApiError
from common.redis import get_redis
from common.spend import spend_key_for

from .bulk import Parsed
from .customers import send_customer_message, upsert_customer
from .models import Campaign, Suppression, Wallet
from .pricing import count_segments, price_for_segments, resolve_sender
from .templates import BULK_PLACEHOLDERS, placeholder_context, render_template, resolve_body, unknown_placeholders

logger = logging.getLogger(__name__)

PROGRESS_EVERY = 25
# Once one of these happens, every remaining number would hit it too: stop instead of looping.
STOP_CODES = {"insufficient_funds", "daily_cap_reached"}


# ---------------------------------------------------------------------------
# Message content
# ---------------------------------------------------------------------------
def resolve_content(org, *, category=None, template_id=None, message=None) -> tuple[str, str]:
    """(body, category) for a bulk message. Refuses tags that wouldn't be filled in."""
    if message:
        body, resolved_category = message.strip(), category or "custom"
    else:
        body, _template, resolved_category = resolve_body(org=org, category=category, template_id=template_id)
    bad = unknown_placeholders(body, BULK_PLACEHOLDERS)
    if bad:
        tags = ", ".join("{" + b + "}" for b in bad)
        raise ApiError(
            "unknown_placeholder",
            f"Your message uses {tags}, which a bulk message can't fill in. "
            "Use {customer_name}, {first_name} or {business_name}.",
        )
    return body, resolved_category


def _render(body: str, org, name: str) -> str:
    return render_template(body, placeholder_context(customer=None, business_name=org.name, customer_name=name))


# ---------------------------------------------------------------------------
# Review (dry run)
# ---------------------------------------------------------------------------
def _balance(org) -> int:
    return Wallet.objects.filter(organization=org).values_list("balance_pesewas", flat=True).first() or 0


def _split_opted_out(org, parsed: Parsed):
    phones = [r["phone"] for r in parsed.recipients]
    opted = set(Suppression.objects.filter(organization=org, recipient__in=phones).values_list("recipient", flat=True))
    sendable = [r for r in parsed.recipients if r["phone"] not in opted]
    return sendable, len(parsed.recipients) - len(sendable)


def _costs(org, body: str, recipients: list[dict]) -> tuple[list[int], int]:
    """Cost in pesewas of each message, and the total number of SMS parts."""
    price_for = {}
    costs, parts = [], 0
    for rec in recipients:
        segments = count_segments(_render(body, org, rec["name"]))
        if segments not in price_for:
            price_for[segments] = price_for_segments(segments)
        costs.append(price_for[segments])
        parts += segments
    return costs, parts


def review(org, parsed: Parsed, *, body: str) -> dict:
    sendable, opted_out = _split_opted_out(org, parsed)
    costs, parts = _costs(org, body, sendable)
    total_cost = sum(costs)
    balance = _balance(org)

    spent_today = int(get_redis().get(spend_key_for(org.id)) or 0)
    room = max(0, org.daily_spend_cap_pesewas - spent_today)
    within_cap, running = 0, 0
    for cost in costs:
        running += cost
        if running > room:
            break
        within_cap += 1

    first = sendable[0] if sendable else (parsed.recipients[0] if parsed.recipients else None)
    return {
        "dry_run": True,
        "summary": {
            "found": parsed.found,
            "valid": len(parsed.recipients),
            "duplicates": parsed.duplicates,
            "invalid": parsed.invalid_count,
            "opted_out": opted_out,
            "to_send": len(sendable),
            "sms_parts": parts,
            "cost_pesewas": total_cost,
            "balance_pesewas": balance,
            "enough_funds": total_cost <= balance,
            "shortfall_pesewas": max(0, total_cost - balance),
            "daily_cap_room_pesewas": room,
            "within_daily_cap": within_cap,
        },
        "invalid": parsed.invalid,
        "warnings": parsed.warnings,
        "sample": {"to": first["phone"], "body": _render(body, org, first["name"])} if first else None,
    }


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def create_campaign(org, user, parsed: Parsed, *, body: str, category: str, sender_id: str | None,
                    save_customers: bool, token: str) -> tuple[Campaign, bool]:
    """Record the batch and queue it. Returns (campaign, created); `created` is False when this
    token was already used, in which case the original batch is returned and nothing new is sent."""
    existing = Campaign.objects.filter(organization=org, client_token=token).first()
    if existing is not None:
        return existing, False

    if sender_id:
        resolve_sender(org, sender_id)            # refuse an unapproved sender before anything is queued

    sendable, opted_out = _split_opted_out(org, parsed)
    if not sendable:
        raise ApiError(
            "no_valid_recipients",
            "There's nobody to send to: every number was invalid, a duplicate, or opted out." if parsed.recipients or parsed.invalid_count
            else "Paste some phone numbers or upload a file first.",
        )
    costs, _ = _costs(org, body, sendable)
    total_cost, balance = sum(costs), _balance(org)
    if total_cost > balance:
        raise ApiError(
            "insufficient_funds",
            f"This needs GHS {total_cost / 100:.2f} but your wallet has GHS {balance / 100:.2f}. Top up first.",
            402, needed_pesewas=total_cost, balance_pesewas=balance,
        )

    try:
        with transaction.atomic():
            campaign = Campaign.objects.create(
                organization=org, created_by=user, client_token=token, category=category, body=body,
                sender=sender_id or "", save_customers=save_customers,
                recipients=sendable, total=len(parsed.recipients), skipped=opted_out,
                skipped_reasons={"recipient_opted_out": opted_out} if opted_out else {},
            )
    except IntegrityError:                        # a concurrent request with the same token won the race
        return Campaign.objects.get(organization=org, client_token=token), False

    transaction.on_commit(lambda: _queue(campaign.id))
    return campaign, True


def _queue(campaign_id):
    from .tasks import run_campaign_task

    try:
        run_campaign_task.delay(str(campaign_id))
    except Exception:
        logger.exception("Could not queue campaign %s", campaign_id)
        # Nothing has been charged yet, so this is safe to mark as never started.
        Campaign.objects.filter(pk=campaign_id, status=Campaign.Status.QUEUED).update(
            status=Campaign.Status.FAILED, finished_at=timezone.now(), recipients=[],
        )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def run_campaign(campaign_id) -> None:
    campaign = Campaign.objects.select_related("organization").filter(pk=campaign_id).first()
    if campaign is None or campaign.status in (Campaign.Status.DONE, Campaign.Status.FAILED):
        return
    Campaign.objects.filter(pk=campaign.pk).update(status=Campaign.Status.RUNNING)

    org = campaign.organization
    recipients = campaign.recipients
    # Opted-out numbers were removed before the run, so they're total minus what's left. Deriving
    # it (instead of reading it back from the saved counters) keeps a re-run from counting twice.
    opted_out = campaign.total - len(recipients)
    reasons: dict[str, int] = {"recipient_opted_out": opted_out} if opted_out else {}
    accepted, skipped, failed = 0, opted_out, 0

    def flush(done=False):
        fields = dict(accepted=accepted, skipped=skipped, failed=failed, skipped_reasons=dict(reasons))
        if done:
            fields.update(status=Campaign.Status.DONE, finished_at=timezone.now(), recipients=[])
        Campaign.objects.filter(pk=campaign.pk).update(**fields)

    for index, rec in enumerate(recipients):
        try:
            _send_one(campaign, org, rec)
            accepted += 1
        except ApiError as exc:
            skipped += 1
            reasons[exc.code] = reasons.get(exc.code, 0) + 1
            if exc.code in STOP_CODES:
                rest = len(recipients) - index - 1
                skipped += rest
                if rest:
                    reasons[exc.code] += rest
                break
        except SoftTimeLimitExceeded:
            flush()                      # keep the progress so far; the task re-queues itself to carry on
            raise
        except Exception:
            logger.exception("Bulk send %s: message to %s failed", campaign.id, rec.get("phone"))
            failed += 1
        if (index + 1) % PROGRESS_EVERY == 0:
            flush()
    flush(done=True)


def _send_one(campaign: Campaign, org, rec: dict) -> dict:
    key = f"bulk:{campaign.id}:{rec['phone']}"
    common = dict(
        org=org, message=campaign.body, category=campaign.category, sender_id=campaign.sender or None,
        idempotency_key=key, campaign=campaign, rate_limit=False,
    )
    if campaign.save_customers:
        birthday = datetime.date.fromisoformat(rec["birthday"]) if rec.get("birthday") else None
        customer = upsert_customer(org, phone=rec["phone"], name=rec["name"], email=rec["email"], birthday=birthday)
        return send_customer_message(customer=customer, customer_name=customer.name, **common)
    return send_customer_message(to=rec["phone"], customer_name=rec["name"], save_customer=False, **common)
