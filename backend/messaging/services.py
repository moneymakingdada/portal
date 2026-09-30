from django.db import transaction

from .ledger import refund_message
from .models import Message


@transaction.atomic
def fail_message(message_id, error_code: str) -> bool:
    """Mark a message failed and refund the customer. Safe to call repeatedly:
    it only acts on messages that are still queued or sent."""
    message = Message.objects.select_for_update().get(pk=message_id)
    if message.status not in (Message.Status.QUEUED, Message.Status.SENT):
        return False
    message.status = Message.Status.FAILED
    message.error_code = error_code[:50]
    message.save(update_fields=["status", "error_code"])
    refund_message(message)
    return True
