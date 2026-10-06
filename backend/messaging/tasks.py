import logging

from celery import shared_task
from django.utils import timezone

from . import providers
from .email_provider import send_email
from .models import Message
from .services import fail_message
from common.errors import ApiError

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_sms(self, message_id: str, body: str):
    """Hand one queued message to the SMS provider.

    `body` carries the real text (including any OTP code). The database only
    ever stores the masked version.
    """
    try:
        message = Message.objects.get(pk=message_id)
    except Message.DoesNotExist:
        logger.error("send_sms: message %s not found", message_id)
        return
    if message.status != Message.Status.QUEUED:
        return  # already handled (e.g. a duplicate delivery of this task)

    provider = providers.get_provider()
    try:
        result = provider.send(sender=message.sender, recipient=message.recipient, body=body)
    except providers.ProviderTransientError as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=5 * 2 ** self.request.retries)
        result = providers.ProviderResult(ok=False, error_code="provider_unreachable", error_message=str(exc))

    if result.ok:
        now = timezone.now()
        Message.objects.filter(pk=message.pk, status=Message.Status.QUEUED).update(
            status=result.status,
            provider=provider.name,
            provider_message_id=result.provider_message_id,
            sent_at=now,
            delivered_at=now if result.status == Message.Status.DELIVERED else None,
        )
    else:
        logger.warning("Message %s failed: %s %s", message_id, result.error_code, result.error_message)
        fail_message(message.pk, result.error_code)


@shared_task(bind=True, max_retries=3)
def send_email_otp(self, message_id: str, subject: str, body: str):
    """Hand one queued email to Django's mail backend (see settings.EMAIL_BACKEND)."""
    try:
        message = Message.objects.get(pk=message_id)
    except Message.DoesNotExist:
        logger.error("send_email_otp: message %s not found", message_id)
        return
    if message.status != Message.Status.QUEUED:
        return  # already handled (e.g. a duplicate delivery of this task)

    try:
        send_email(to=message.recipient, subject=subject, body=body, from_email=message.sender)
    except ApiError as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=5 * 2 ** self.request.retries)
        logger.warning("Email %s failed after retries: %s", message_id, exc.message)
        fail_message(message.pk, "provider_unreachable")
        return

    now = timezone.now()
    Message.objects.filter(pk=message.pk, status=Message.Status.QUEUED).update(
        status=Message.Status.DELIVERED, provider="smtp", sent_at=now, delivered_at=now,
    )


@shared_task
def send_birthday_messages_task():
    """Runs once a day (see CELERY_BEAT_SCHEDULE in config/settings.py)."""
    from .customers import send_birthday_messages

    result = send_birthday_messages()
    logger.info("Birthday messages for %s: sent=%s skipped=%s failed=%s",
                result["date"], result["sent"], result["skipped"], result["failed"])
    return result