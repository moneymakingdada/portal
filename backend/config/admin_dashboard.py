"""Numbers for the admin home page (wired up by UNFOLD["DASHBOARD_CALLBACK"]).

Everything here is a handful of cheap aggregate queries, run once per page
load by staff only. Money is integer pesewas everywhere else; it is only
turned into "GHS 12.50" text at the very edge, here.
"""
import json
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from messaging.models import Message, Organization, Payment, SenderId, Wallet

CHART_DAYS = 14


def ghs(pesewas: int) -> str:
    return f"GHS {pesewas / 100:,.2f}"


def _message_chart(now):
    start = (now - timedelta(days=CHART_DAYS - 1)).date()
    rows = (
        Message.objects.filter(created_at__date__gte=start)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(
            delivered=Count("id", filter=Q(status=Message.Status.DELIVERED)),
            in_flight=Count("id", filter=Q(status__in=[Message.Status.QUEUED, Message.Status.SENT])),
            failed=Count("id", filter=Q(status__in=[Message.Status.FAILED, Message.Status.EXPIRED])),
        )
    )
    by_day = {row["day"]: row for row in rows}
    days = [start + timedelta(days=i) for i in range(CHART_DAYS)]

    def series(key):
        return [by_day.get(day, {}).get(key, 0) for day in days]

    data = {
        "labels": [day.strftime("%d %b") for day in days],
        "datasets": [
            {"label": "Delivered", "data": series("delivered"), "backgroundColor": "var(--color-primary-600)"},
            {"label": "Sent / queued", "data": series("in_flight"), "backgroundColor": "var(--color-primary-300)"},
            {"label": "Failed", "data": series("failed"), "backgroundColor": "#c0392b"},
        ],
    }
    options = {"aspectRatio": 3.4, "scales": {"x": {"stacked": True}, "y": {"stacked": True, "beginAtZero": True}}}
    return json.dumps(data), json.dumps(options)


def _recent_failures():
    failed = (
        Message.objects.filter(status__in=[Message.Status.FAILED, Message.Status.EXPIRED])
        .select_related("organization")
        .order_by("-created_at")[:8]
    )
    rows = [
        [
            timezone.localtime(m.created_at).strftime("%d %b %H:%M"),
            m.organization.name,
            m.recipient,
            m.error_code or "unknown",
        ]
        for m in failed
    ]
    return {"headers": ["When", "Organization", "To", "Reason"], "rows": rows}


def dashboard_callback(request, context):
    now = timezone.localtime()
    day_ago = now - timedelta(hours=24)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    last_day = Message.objects.filter(created_at__gte=day_ago).aggregate(
        total=Count("id"),
        delivered=Count("id", filter=Q(status=Message.Status.DELIVERED)),
        failed=Count("id", filter=Q(status__in=[Message.Status.FAILED, Message.Status.EXPIRED])),
    )
    revenue = Payment.objects.filter(status=Payment.Status.SUCCESS, created_at__gte=month_start).aggregate(
        total=Sum("amount_pesewas")
    )["total"] or 0
    held = Wallet.objects.aggregate(total=Sum("balance_pesewas"))["total"] or 0
    pending_senders = SenderId.objects.filter(status=SenderId.Status.PENDING).count()
    orgs = Organization.objects.aggregate(total=Count("id"), active=Count("id", filter=Q(is_active=True)))

    sent = last_day["total"]
    rate = f"{round(100 * last_day['delivered'] / sent)}% delivered" if sent else "No messages yet"
    chart, chart_options = _message_chart(now)

    context.update(
        {
            "kpis": [
                {
                    "title": "Messages, last 24h",
                    "value": f"{sent:,}",
                    "footer": f"{rate} · {last_day['failed']:,} failed",
                    "icon": "sms",
                    "href": reverse("admin:messaging_message_changelist"),
                },
                {
                    "title": "Top-ups this month",
                    "value": ghs(revenue),
                    "footer": "Successful payments",
                    "icon": "payments",
                    "href": reverse("admin:messaging_payment_changelist") + "?status__exact=success",
                },
                {
                    "title": "Wallet balances",
                    "value": ghs(held),
                    "footer": "Prepaid credit held for customers",
                    "icon": "account_balance_wallet",
                    "href": reverse("admin:messaging_wallet_changelist"),
                },
                {
                    "title": "Organizations",
                    "value": f"{orgs['active']:,}",
                    "footer": f"{User.objects.count():,} users · {orgs['total'] - orgs['active']:,} suspended",
                    "icon": "business",
                    "href": reverse("admin:messaging_organization_changelist"),
                },
                {
                    "title": "Pending senders",
                    "value": f"{pending_senders:,}",
                    "footer": "Waiting on your approval",
                    "icon": "badge",
                    "href": reverse("admin:messaging_senderid_changelist") + "?status__exact=pending",
                    "attention": pending_senders > 0,
                },
            ],
            "chart": chart,
            "chart_options": chart_options,
            "chart_days": CHART_DAYS,
            "failures": _recent_failures(),
        }
    )
    return context
