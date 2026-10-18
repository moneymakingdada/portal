"""Texting the people who run the platform (staff/superusers) when something
needs their attention: a new sign-up, a new sender ID request, ...

Recipients: every active staff/superuser with a phone number on their profile
(set it in the admin), plus any extra numbers in ADMIN_ALERT_PHONES. Alerts are
best effort and platform-paid: the thing being reported has already happened,
so one unreachable number must never fail the request or block the others.
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q

from common.phone import InvalidPhone, normalize_gh_number

from .providers import send_platform_sms

logger = logging.getLogger(__name__)

MAX_ADMIN_ALERTS = 10   # never fan one event out to more numbers than this


def admin_alert_numbers(exclude: str | None = None) -> list[str]:
    """De-duplicated, capped list of E.164 numbers to alert. `exclude` skips
    one number, e.g. the person who triggered the event."""
    User = get_user_model()
    staff = (
        User.objects.filter(is_active=True)
        .filter(Q(is_staff=True) | Q(is_superuser=True))
        .exclude(phone__isnull=True).exclude(phone="")
        .order_by("date_joined")
        .values_list("phone", flat=True)
    )
    numbers = list(staff)
    for raw in settings.ADMIN_ALERT_PHONES:
        try:
            numbers.append(normalize_gh_number(raw))
        except InvalidPhone:
            logger.warning("Ignoring invalid ADMIN_ALERT_PHONES entry %r", raw)
    unique = list(dict.fromkeys(n for n in numbers if n != exclude))
    return unique[:MAX_ADMIN_ALERTS]


def notify_admins(body: str, *, exclude: str | None = None) -> int:
    """Text `body` to every admin number. Returns how many sends succeeded."""
    sent = 0
    for number in admin_alert_numbers(exclude=exclude):
        try:
            send_platform_sms(number, body)
            sent += 1
        except Exception:
            logger.warning("Admin alert to %s failed; the action itself succeeded", number, exc_info=True)
    return sent
