import logging

from celery import shared_task
from django.utils import timezone

from . import providers
from .models import Message
from .services import fail_message

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


@shared_task(bind=True, time_limit=900, soft_time_limit=840)
def run_campaign_task(self, campaign_id: str):
    """Send a bulk batch in the background (see campaigns.run_campaign). If the time limit is
    reached partway through a very large batch, queue it again: numbers already sent are
    replayed from their idempotency keys, so nothing is charged twice."""
    from celery.exceptions import SoftTimeLimitExceeded

    from .campaigns import run_campaign

    try:
        run_campaign(campaign_id)
    except SoftTimeLimitExceeded:
        logger.warning("Bulk send %s hit the time limit; queueing it again to continue", campaign_id)
        run_campaign_task.apply_async(args=[campaign_id], countdown=1)


@shared_task
def send_birthday_messages_task():
    """Runs once a day (see CELERY_BEAT_SCHEDULE in config/settings.py)."""
    from .customers import send_birthday_messages

    result = send_birthday_messages()
    logger.info("Birthday messages for %s: sent=%s skipped=%s failed=%s",
                result["date"], result["sent"], result["skipped"], result["failed"])
    return result


@shared_task
def alert_admins_of_sender_request(sender_pk: int, resubmitted: bool = False):
    """Text the admins that a sender ID request is waiting for review. Runs in
    the background so a slow SMS provider never delays the customer's upload."""
    from django.conf import settings

    from .admin_alerts import notify_admins
    from .models import SenderId

    if not settings.ADMIN_SENDER_ALERTS_ENABLED:
        return
    sender = SenderId.objects.select_related("organization").filter(pk=sender_pk).first()
    if sender is None or sender.status != SenderId.Status.PENDING:
        return  # withdrawn or already decided since it was submitted
    body = (
        f"{settings.APP_NAME}: sender ID request{' (resubmitted)' if resubmitted else ''}. "
        f"{sender.name} from {sender.organization.name[:40]} "
        f"({'business' if sender.is_business else 'individual'}). Review in Admin > Sender IDs."
    )
    if settings.BACKEND_URL:
        body += f" {settings.BACKEND_URL}/admin/messaging/senderid/"
    notify_admins(body)


@shared_task
def notify_owner_of_sender_decision(sender_pk: int, decision: str):
    """Text the account owner that their sender ID request was approved or
    rejected. Skipped if the request has changed again since (so a quick
    approve-then-reject never sends the stale message)."""
    from django.conf import settings

    from .models import SenderId

    if not settings.SENDER_DECISION_SMS_ENABLED:
        return
    sender = SenderId.objects.select_related("organization__owner").filter(pk=sender_pk).first()
    if sender is None or sender.status != decision:
        return
    phone = getattr(sender.organization.owner, "phone", None)
    if not phone:
        return
    if decision == SenderId.Status.APPROVED:
        body = (f'{settings.APP_NAME}: your sender ID "{sender.name}" is approved. '
                "You can now use it when you send messages.")
    elif decision == SenderId.Status.REJECTED:
        reason = (sender.rejection_reason or "We couldn't verify your documents.")[:120]
        body = (f'{settings.APP_NAME}: your sender ID "{sender.name}" was not approved. {reason} '
                "Fix it and resubmit from your dashboard.")
    else:
        return
    try:
        providers.send_platform_sms(phone, body)
    except Exception:
        logger.warning("Sender ID decision text to %s failed; the decision itself stands", phone, exc_info=True)
