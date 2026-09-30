"""
Per-organization daily spend cap. One counter covers every kind of send (OTP
codes, thank-you notes, birthday wishes, ...) since it exists to protect the
org's wallet from a runaway loop, not to police any one feature.

Redis layout:
    spend:{org}:{YYYYMMDD}   total pesewas spent by this organization today
"""
from django.utils import timezone

from .errors import ApiError


def spend_key_for(org_id) -> str:
    return f"spend:{org_id}:{timezone.now().strftime('%Y%m%d')}"


def check_daily_cap(r, org, cost: int) -> str:
    """Raise ApiError(403) if sending now would push today's total spend past
    the organization's daily cap. Returns the spend key to pass to
    record_spend() once the send actually goes out."""
    key = spend_key_for(org.id)
    if cost > 0 and int(r.get(key) or 0) + cost > org.daily_spend_cap_pesewas:
        raise ApiError("daily_cap_reached", "Daily spend cap reached for this account.", 403)
    return key


def record_spend(r, spend_key: str, cost: int) -> None:
    if cost <= 0:
        return
    r.incrby(spend_key, cost)
    r.expire(spend_key, 172_800)  # two days: comfortably outlives the "today" window it's keyed by
