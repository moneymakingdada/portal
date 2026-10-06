"""Shared SMS pricing and sender-ID resolution, used by both OTP and customer messages."""
from django.conf import settings

from common.errors import ApiError

from .models import PricingTier, SenderId


def count_segments(text: str) -> int:
    """Approximation: ASCII -> 160 (153 when split) per segment, otherwise Unicode 70 (67).
    Real GSM-7 also includes some non-ASCII characters and charges "extended"
    characters double, so treat this as an estimate."""
    single, multi = (160, 153) if text.isascii() else (70, 67)
    n = len(text)
    return 1 if n <= single else -(-n // multi)


def price_for_segments(segments: int) -> int:
    # One default tier for now. Extend with per-network and monthly-volume tiers
    # once you record the network from delivery reports.
    tier = PricingTier.objects.filter(network="").order_by("min_monthly_volume").first()
    if tier is None:
        return settings.DEFAULT_PRICE_PER_SEGMENT_PESEWAS * segments
    return tier.otp_price_pesewas or tier.price_per_segment_pesewas * segments


def resolve_sender(org, requested: str | None) -> str:
    if not requested:
        return settings.DEFAULT_SENDER_ID
    approved = SenderId.objects.filter(
        organization=org, channel=SenderId.Channel.SMS, name=requested, status=SenderId.Status.APPROVED
    ).exists()
    if not approved:
        raise ApiError("sender_not_approved", "That sender ID isn't approved for this account.")
    return requested


def resolve_email_sender(org, requested_name: str | None) -> str:
    """Returns the email "From" header: always the platform's own verified
    address, with an approved display name in front of it if one was asked
    for. The address itself is never customer-controlled - sending from an
    unverified domain fails SPF/DKIM checks and looks like spoofing."""
    if not requested_name:
        return settings.DEFAULT_FROM_EMAIL
    approved = SenderId.objects.filter(
        organization=org, channel=SenderId.Channel.EMAIL, name=requested_name, status=SenderId.Status.APPROVED
    ).exists()
    if not approved:
        raise ApiError("sender_not_approved", "That sender name isn't approved for this account.")
    address = settings.DEFAULT_FROM_EMAIL.split("<")[-1].rstrip(">").strip()
    return f"{requested_name} <{address}>"