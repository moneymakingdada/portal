from django.conf import settings
from django.db import models

import uuid


class Conversation(models.Model):
    """One chat with the assistant. Belongs to a user inside one organization."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("messaging.Organization", on_delete=models.CASCADE, related_name="support_conversations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class Turn(models.Model):
    """One message in a chat. Only the words are kept (not tool output), so the
    history sent back to the model never contains data it could be tricked by."""
    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="turns")
    role = models.CharField(max_length=10, choices=Role.choices)
    text = models.TextField()
    tools_used = models.JSONField(default=list, blank=True)    # names only, for auditing what the bot looked at
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class Ticket(models.Model):
    """A problem the assistant couldn't fix, or that the customer sent straight to staff."""
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ANSWERED = "answered", "Answered"
        CLOSED = "closed", "Closed"

    organization = models.ForeignKey("messaging.Organization", on_delete=models.CASCADE, related_name="tickets")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    conversation = models.ForeignKey(Conversation, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    subject = models.CharField(max_length=140)
    details = models.TextField(max_length=2000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    staff_reply = models.TextField(blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    replied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reply_texted = models.BooleanField(default=False)          # did the SMS about the reply go out
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.subject}"
