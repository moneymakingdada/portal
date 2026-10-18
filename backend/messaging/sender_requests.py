"""
Sender ID requests: an organization asks to send under its own name (e.g.
"ACME") instead of the platform default, uploading the paperwork the telcos
want: a signed letter of authorization, plus a business certificate (for a
business) or a Ghana Card (for an individual).

Staff review the documents in the admin and approve or reject. Approving here
is the platform's decision; the name still has to be whitelisted with the SMS
provider/telco before messages under it will actually deliver.
"""
import os
import re

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from common.errors import ApiError

from .models import SenderId, SenderIdDocument

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_SENDERS_PER_ORG = 10
MAX_PENDING_PER_ORG = 3     # also caps how many alert texts one organization can trigger

# 3-11 characters, letters/digits/spaces only, starting and ending with a letter or digit.
SENDER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ]{1,9}[A-Za-z0-9]$")

# extension -> (content type we serve it back as, magic-number prefixes)
_FILE_TYPES = {
    ".pdf": ("application/pdf", (b"%PDF",)),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", (b"PK\x03\x04",)),
    ".doc": ("application/msword", (b"\xd0\xcf\x11\xe0",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
}
ALLOWED_EXTENSIONS = {
    SenderIdDocument.Kind.LETTER: (".pdf", ".docx", ".doc"),
    SenderIdDocument.Kind.SUPPORTING: (".pdf", ".jpg", ".jpeg", ".png"),
}


def validate_sender_name(value: str) -> str:
    from django.conf import settings

    name = " ".join(value.split())
    if not SENDER_NAME_RE.match(name) or not re.search(r"[A-Za-z]", name):
        raise serializers.ValidationError(
            "Use 3 to 11 letters, numbers or spaces, with at least one letter (no symbols)."
        )
    if name.lower() == settings.DEFAULT_SENDER_ID.lower():
        raise serializers.ValidationError("That name is reserved by the platform. Choose another.")
    return name


def read_document(upload, kind: str) -> dict:
    """Validate an uploaded file and return the fields to store. The type is
    decided from the extension plus the file's own first bytes, never from the
    browser-supplied content type, and the file is only ever served back as a
    download to staff."""
    filename = os.path.basename((upload.name or "").replace("\\", "/"))
    filename = "".join(ch for ch in filename if ch.isprintable())[:200].strip()
    ext = os.path.splitext(filename)[1].lower()
    allowed = ALLOWED_EXTENSIONS[kind]
    if ext not in allowed:
        raise serializers.ValidationError(
            "Upload a " + ", ".join(e.lstrip(".").upper() for e in allowed[:-1])
            + (" or " if len(allowed) > 1 else "") + allowed[-1].lstrip(".").upper() + " file."
        )
    if upload.size > MAX_UPLOAD_BYTES:
        raise serializers.ValidationError(f"That file is too large. The limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    data = upload.read()
    if not data:
        raise serializers.ValidationError("That file is empty.")
    content_type, magics = _FILE_TYPES[ext]
    if not data.startswith(magics):
        raise serializers.ValidationError("That file doesn't look like a real " + ext.lstrip(".").upper() + ".")
    return {"filename": filename, "content_type": content_type, "size": len(data), "data": data}


class SenderRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=40)
    purpose = serializers.CharField(min_length=10, max_length=300)
    is_business = serializers.BooleanField(default=False)
    letter = serializers.FileField(allow_empty_file=True)
    supporting = serializers.FileField(allow_empty_file=True)

    def validate_name(self, value):
        return validate_sender_name(value)

    def validate_purpose(self, value):
        return value.strip()

    def validate_letter(self, upload):
        return read_document(upload, SenderIdDocument.Kind.LETTER)

    def validate_supporting(self, upload):
        return read_document(upload, SenderIdDocument.Kind.SUPPORTING)


@transaction.atomic
def submit_sender_request(org, data: dict) -> tuple[SenderId, bool]:
    """Create a pending request, or resubmit a rejected one. Returns
    (sender, resubmitted)."""
    name = data["name"]
    mine = SenderId.objects.select_for_update().filter(organization=org)
    existing = next((s for s in mine if s.name.lower() == name.lower()), None)

    if existing and existing.status != SenderId.Status.REJECTED:
        raise ApiError(
            "sender_exists",
            "You've already requested that sender ID." if existing.status == SenderId.Status.PENDING
            else "That sender ID is already approved on your account.",
            409,
        )
    if SenderId.objects.filter(name__iexact=name, status=SenderId.Status.APPROVED).exclude(organization=org).exists():
        raise ApiError("sender_name_taken", "That sender ID already belongs to another account.", 409)
    if existing is None and len(mine) >= MAX_SENDERS_PER_ORG:
        raise ApiError("sender_limit", f"You can have at most {MAX_SENDERS_PER_ORG} sender IDs. Withdraw one first.")
    if sum(1 for s in mine if s.status == SenderId.Status.PENDING) >= MAX_PENDING_PER_ORG:
        raise ApiError(
            "too_many_pending",
            f"You already have {MAX_PENDING_PER_ORG} requests waiting for review. Wait for a decision first.",
            429,
        )

    fields = {
        "name": name,
        "purpose": data["purpose"],
        "is_business": data["is_business"],
        "status": SenderId.Status.PENDING,
        "rejection_reason": "",
        "submitted_at": timezone.now(),
        "reviewed_at": None,
        "reviewed_by": None,
    }
    if existing:
        for key, value in fields.items():
            setattr(existing, key, value)
        existing.save()
        sender = existing
    else:
        sender = SenderId.objects.create(organization=org, **fields)

    for kind, key in ((SenderIdDocument.Kind.LETTER, "letter"), (SenderIdDocument.Kind.SUPPORTING, "supporting")):
        SenderIdDocument.objects.update_or_create(sender_id=sender, kind=kind, defaults=data[key])
    return sender, existing is not None


def queue_decision_text(sender: SenderId) -> None:
    """After staff approve or reject a request, text the owner once the change
    is committed. Never raises: the decision is already made."""
    import logging

    from .tasks import notify_owner_of_sender_decision

    if sender.status not in (SenderId.Status.APPROVED, SenderId.Status.REJECTED):
        return
    pk, decision = sender.pk, sender.status

    def queue():
        try:
            notify_owner_of_sender_decision.delay(pk, decision)
        except Exception:
            logging.getLogger(__name__).warning("Couldn't queue the decision text for sender %s", pk, exc_info=True)

    transaction.on_commit(queue)
