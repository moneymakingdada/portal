"""Opening tickets and answering them. Used by the chat bot, the "contact us" form and the admin."""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.errors import ApiError
from common.ratelimit import hit
from messaging.admin_alerts import notify_admins
from messaging.providers import send_platform_sms

from .models import Ticket

logger = logging.getLogger(__name__)

MAX_SUBJECT = 140
MAX_DETAILS = 2000
TICKETS_PER_ORG_PER_DAY = 10
TICKETS_PER_CHAT = 2


def open_ticket(org, user, *, subject: str, details: str, conversation=None) -> Ticket:
    subject, details = " ".join((subject or "").split())[:MAX_SUBJECT], (details or "").strip()[:MAX_DETAILS]
    if not subject or not details:
        raise ApiError("ticket_incomplete", "Add a short title and a few details so our team can help.")
    if conversation is not None and conversation.tickets.count() >= TICKETS_PER_CHAT:
        raise ApiError("ticket_already_open",
                       "A ticket from this chat is already with our team. They'll reply there.", 409)
    hit(f"rl:tickets:org:{org.id}", limit=TICKETS_PER_ORG_PER_DAY, window=86400, code="tickets_rate_limited",
        message="You've sent a lot of tickets today. Our team will get to them; please wait for a reply.")
    ticket = Ticket.objects.create(organization=org, user=user, conversation=conversation,
                                   subject=subject, details=details)
    if settings.ADMIN_TICKET_ALERTS_ENABLED:
        text = f"New support ticket #{ticket.pk} from {org.name[:40]}: {subject[:80]}"
        transaction.on_commit(lambda: notify_admins(text))
    return ticket


def reply_to_ticket(ticket: Ticket, staff_user, reply: str) -> bool:
    """Record a staff reply and text the customer. Returns whether the text went out.
    The reply is saved either way; the customer can always read it on the support page."""
    ticket.staff_reply = reply.strip()
    ticket.replied_at = timezone.now()
    ticket.replied_by = staff_user
    if ticket.status == Ticket.Status.OPEN:
        ticket.status = Ticket.Status.ANSWERED
    texted = False
    phone = getattr(ticket.user, "phone", None) if ticket.user_id else None
    if phone and settings.TICKET_REPLY_SMS_ENABLED:
        try:
            send_platform_sms(
                phone,
                f"{settings.APP_NAME} support, ticket #{ticket.pk}: {ticket.staff_reply[:280]} "
                "(Full reply is in your dashboard under Support.)",
            )
            texted = True
        except Exception:
            logger.warning("Could not text the reply to ticket %s", ticket.pk, exc_info=True)
    ticket.reply_texted = texted
    ticket.save()
    return texted
