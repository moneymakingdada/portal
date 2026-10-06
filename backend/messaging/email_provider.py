# messaging/email_provider.py
import logging
import smtplib
from email.utils import parseaddr

from django.conf import settings
from django.core.mail import BadHeaderError, EmailMessage

from common.errors import ApiError

logger = logging.getLogger(__name__)

# Retrying can't fix these: the address or header itself is the problem.
_PERMANENT = (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, BadHeaderError)


def send_email(*, to: str, subject: str, body: str, from_email: str | None = None) -> None:
    """Send one plain-text email through Django's EMAIL_BACKEND.

    from_email is Message.sender, i.e. what resolve_email_sender() returned.
    Raises ApiError("email_rejected") for failures that retrying won't fix,
    and ApiError("email_unreachable") for transient ones.
    """
    # Cheap guard in case a stored sender ever contains a line break.
    if any(c in (from_email or "") + subject for c in "\r\n"):
        raise ApiError("email_rejected", "Header contains a line break.")

    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=[to],
    )
    try:
        sent = msg.send(fail_silently=False)
    except _PERMANENT as exc:
        logger.warning("Email to %s rejected: %s", to, exc)
        raise ApiError("email_rejected", str(exc)) from exc
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("Email to %s failed: %s", to, exc)
        raise ApiError("email_unreachable", str(exc), 502) from exc

    if sent != 1:
        raise ApiError("email_unreachable", "Email backend reported no messages sent.", 502)