"""
Core models for the messaging platform: organizations and API keys, the wallet
ledger, messages, and OTP audit records. All money is integer pesewas (100 = GHS 1).
"""
import uuid
from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Accounts / API access
# ---------------------------------------------------------------------------
class Organization(models.Model):
    """A customer of your platform (the business sending messages)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="organizations")
    is_active = models.BooleanField(default=True)
    # Fraud / cost protection (SMS pumping)
    daily_spend_cap_pesewas = models.BigIntegerField(default=50_000)  # GHS 500
    # Automatic birthday messages to customers (see Customer, MessageTemplate below)
    birthday_messages_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ApiKey(models.Model):
    """Store only a hash of the key; show the full key once at creation."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=16, db_index=True)   # first 16 chars, e.g. "sk_live_ab12cd34", for lookup
    key_hash = models.CharField(max_length=128)                # SHA-256 of the full key
    is_live = models.BooleanField(default=False)               # test keys never hit a provider
    allowed_ips = models.JSONField(default=list, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SenderId(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="sender_ids")
    name = models.CharField(max_length=11)                     # 11-char limit
    purpose = models.TextField(blank=True)                     # sample message for approval
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="uniq_org_sender")]


# ---------------------------------------------------------------------------
# Customer messaging: an organization's own customers, and the message
# templates (thank-you, birthday, holiday, welcome, custom) it sends them.
# Separate from OtpRequest below, which is about verifying a phone number,
# not building a relationship with the person who owns it.
# ---------------------------------------------------------------------------
class Customer(models.Model):
    """One of an organization's customers - who they message, not who logs in."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="customers")
    phone = models.CharField(max_length=16, db_index=True)  # E.164, e.g. +233241234567
    name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    birthday = models.DateField(null=True, blank=True)  # year is stored but ignored; only month/day are used
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "phone"], name="uniq_org_customer_phone")]
        indexes = [models.Index(fields=["organization", "birthday"])]

    def __str__(self):
        return self.name or self.phone


class MessageTemplate(models.Model):
    """A reusable message body for a category of customer message.

    `body` may contain {customer_name}, {business_name} and {amount}
    placeholders, filled in at send time (see messaging/templates.py).
    An organization can have several templates per category; `is_default`
    marks the one automatic sends (like birthdays) and the bare `category`
    shorthand on the send API use.
    """
    class Category(models.TextChoices):
        THANK_YOU = "thank_you"
        BIRTHDAY = "birthday"
        HOLIDAY = "holiday"
        WELCOME = "welcome"
        CUSTOM = "custom"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="templates")
    category = models.CharField(max_length=20, choices=Category.choices)
    name = models.CharField(max_length=100)
    body = models.CharField(max_length=480)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "category"])]
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return f"{self.name} ({self.category})"


# ---------------------------------------------------------------------------
# Wallet: append-only ledger. Never edit or delete entries.
# All money in pesewas (integer) to avoid float errors. 100 pesewas = GHS 1.
# ---------------------------------------------------------------------------
class Wallet(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="wallet")
    # Cached balance, updated in the same transaction as each ledger entry
    # using select_for_update(). The ledger is the source of truth.
    balance_pesewas = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(balance_pesewas__gte=0), name="wallet_non_negative"),
        ]


class LedgerEntry(models.Model):
    class Kind(models.TextChoices):
        TOPUP = "topup"          # + money in via Paystack / MoMo
        DEBIT = "debit"          # - message sent
        REFUND = "refund"        # + failed delivery reversal
        ADJUSTMENT = "adjustment"  # +/- manual, admin only

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="entries")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    amount_pesewas = models.BigIntegerField()                  # signed: + credit, - debit
    balance_after_pesewas = models.BigIntegerField()
    # Idempotency: same key can never post twice (webhook retries, double clicks)
    idempotency_key = models.CharField(max_length=160, unique=True)
    message = models.ForeignKey("Message", null=True, blank=True, on_delete=models.PROTECT)
    payment = models.ForeignKey("Payment", null=True, blank=True, on_delete=models.PROTECT)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class Payment(models.Model):
    """A top-up attempt through Paystack / Hubtel / MoMo."""
    class Status(models.TextChoices):
        PENDING = "pending"
        SUCCESS = "success"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    provider = models.CharField(max_length=20)                 # paystack | hubtel
    provider_reference = models.CharField(max_length=120, unique=True)
    amount_pesewas = models.BigIntegerField()
    plan = models.ForeignKey("SmsPlan", null=True, blank=True, on_delete=models.SET_NULL, related_name="payments")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    # Whatever the provider last told us about this payment: a webhook body or
    # the response to a verify call, kept for debugging disputes.
    raw_response = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SmsPlan(models.Model):
    """A purchasable top-up bundle shown on the Buy SMS page.

    Buying a plan credits the wallet with `price_pesewas` - the same money a
    custom top-up would add. `message_count` is what the price buys at
    current rates, shown so people can compare plans; the wallet itself only
    ever holds cedis, and wallet credit never expires.
    """
    name = models.CharField(max_length=120)
    price_pesewas = models.BigIntegerField()
    message_count = models.PositiveIntegerField()
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "price_pesewas"]
        constraints = [
            models.CheckConstraint(condition=models.Q(price_pesewas__gt=0), name="smsplan_price_positive"),
        ]

    def __str__(self):
        return self.name


class PricingTier(models.Model):
    """Per-segment price, optionally per network and volume band."""
    network = models.CharField(max_length=10, blank=True)      # "" = default; mtn | telecel | at
    min_monthly_volume = models.IntegerField(default=0)
    price_per_segment_pesewas = models.IntegerField()
    otp_price_pesewas = models.IntegerField(null=True, blank=True)  # premium per-verification


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------
class Message(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        SENT = "sent"            # accepted by upstream
        DELIVERED = "delivered"  # DLR confirmed
        FAILED = "failed"
        EXPIRED = "expired"

    class Channel(models.TextChoices):
        SMS = "sms"
        EMAIL = "email"
        VOICE = "voice"
        WHATSAPP = "whatsapp"

    class Category(models.TextChoices):
        OTP = "otp"
        THANK_YOU = "thank_you"
        BIRTHDAY = "birthday"
        HOLIDAY = "holiday"
        WELCOME = "welcome"
        CUSTOM = "custom"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="messages")
    api_key = models.ForeignKey(ApiKey, null=True, on_delete=models.SET_NULL)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.SMS)
    category = models.CharField(max_length=20, choices=Category.choices, blank=True)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages")
    template = models.ForeignKey(MessageTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages")
    sender = models.CharField(max_length=11)
    recipient = models.CharField(max_length=16, db_index=True)  # E.164, e.g. +233241234567
    body = models.TextField()
    segments = models.PositiveSmallIntegerField(default=1)
    cost_pesewas = models.IntegerField(default=0)               # what the customer pays
    provider_cost_pesewas = models.IntegerField(default=0)      # what upstream charges you (margin)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    network = models.CharField(max_length=10, blank=True)       # from DLR, not from the prefix
    provider = models.CharField(max_length=30, blank=True)      # which upstream carried it
    provider_message_id = models.CharField(max_length=120, blank=True, db_index=True)
    error_code = models.CharField(max_length=50, blank=True)
    idempotency_key = models.CharField(max_length=120, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "-created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uniq_org_message_idem",
            )
        ]


class DeliveryEvent(models.Model):
    """Raw DLR / status callbacks from upstream. Keep for debugging disputes."""
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=20)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)


class WebhookEndpoint(models.Model):
    """Customer callback URLs for delivery reports."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="webhooks")
    url = models.URLField()
    secret = models.CharField(max_length=64)                    # for HMAC signature header
    events = models.JSONField(default=list)                     # ["message.delivered", "otp.verified"]
    is_active = models.BooleanField(default=True)


class Suppression(models.Model):
    """Opt-outs / do-not-contact list, per organization."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    recipient = models.CharField(max_length=16)
    reason = models.CharField(max_length=50, default="opt_out")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "recipient"], name="uniq_suppression")]


# ---------------------------------------------------------------------------
# OTP
# Hot path lives in Redis (code hash, TTL, attempts, cooldown).
# This table is the durable audit record, so customers can see history.
# ---------------------------------------------------------------------------
class OtpRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        VERIFIED = "verified"
        EXPIRED = "expired"
        LOCKED = "locked"       # too many wrong attempts
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # returned as request_id
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="otp_requests")
    recipient = models.CharField(max_length=16, db_index=True)
    channel = models.CharField(max_length=10, default="sms")
    purpose = models.CharField(max_length=50, blank=True)       # login | signup | payment
    code_hash = models.CharField(max_length=128)                # HMAC-SHA256(code, per-request salt); never plaintext
    code_length = models.PositiveSmallIntegerField(default=6)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    resend_count = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    message = models.ForeignKey(Message, null=True, on_delete=models.SET_NULL)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "recipient", "-created_at"])]
