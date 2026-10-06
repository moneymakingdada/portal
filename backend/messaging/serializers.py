from rest_framework import serializers

from common.phone import InvalidPhone, normalize_gh_number

from .models import ApiKey, Customer, LedgerEntry, Message, MessageTemplate, SenderId, SmsPlan


class ApiKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = ApiKey
        fields = ["id", "name", "prefix", "is_live", "created_at", "last_used_at", "revoked_at"]
        read_only_fields = fields


class ApiKeyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=1, max_length=60)
    live = serializers.BooleanField(default=False)

    def validate_name(self, value):
        return value.strip()


class MessageSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", default="", read_only=True)

    class Meta:
        model = Message
        fields = ["id", "recipient", "sender", "channel", "category", "status", "segments",
                  "cost_pesewas", "network", "error_code", "customer_id", "customer_name",
                  "created_at", "sent_at", "delivered_at"]
        read_only_fields = fields


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = ["id", "kind", "amount_pesewas", "balance_after_pesewas", "note", "created_at"]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "phone", "name", "email", "birthday", "notes", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_phone(self, value):
        try:
            return normalize_gh_number(value)
        except InvalidPhone as exc:
            raise serializers.ValidationError(str(exc))


class CustomerWriteSerializer(CustomerSerializer):
    """Same shape as CustomerSerializer, but every field is optional for PATCH."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if kwargs.get("partial"):
            for field in self.fields.values():
                field.required = False


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
class MessageTemplateSerializer(serializers.ModelSerializer):
    is_suggested = serializers.SerializerMethodField()

    class Meta:
        model = MessageTemplate
        fields = ["id", "category", "name", "body", "is_default", "is_suggested", "created_at", "updated_at"]
        read_only_fields = ["id", "is_suggested", "created_at", "updated_at"]

    def get_is_suggested(self, obj):
        return False  # always False for real rows; the suggested-defaults list is synthesized in the view


class MessageTemplateWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageTemplate
        fields = ["category", "name", "body", "is_default"]

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Template text can't be empty.")
        return value


# ---------------------------------------------------------------------------
# Sending a customer message
# ---------------------------------------------------------------------------
class SendCustomerMessageSerializer(serializers.Serializer):
    to = serializers.CharField(max_length=32, required=False)
    category = serializers.ChoiceField(choices=MessageTemplate.Category.choices, required=False)
    template_id = serializers.UUIDField(required=False)
    message = serializers.CharField(max_length=480, required=False, allow_blank=False)
    customer_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=0)
    sender_id = serializers.CharField(max_length=11, required=False)
    save_customer = serializers.BooleanField(default=True)

    def validate(self, attrs):
        if not any(k in attrs for k in ("category", "template_id", "message")):
            raise serializers.ValidationError("Provide a template_id, a category, or a message.")
        return attrs


# ---------------------------------------------------------------------------
# Top-ups and plans
# ---------------------------------------------------------------------------
class SmsPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SmsPlan
        fields = ["id", "name", "price_pesewas", "message_count", "is_popular"]
        read_only_fields = fields


class TopupStartSerializer(serializers.Serializer):
    """Buy a listed plan (`plan_id`) or add a custom amount in GHS (`amount`) - one or the other."""
    plan_id = serializers.IntegerField(required=False)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=0)

    def validate(self, attrs):
        if ("plan_id" in attrs) == ("amount" in attrs):
            raise serializers.ValidationError("Provide either plan_id or amount.")
        return attrs


# ---------------------------------------------------------------------------
# Sender IDs
# ---------------------------------------------------------------------------
class SenderIdSerializer(serializers.ModelSerializer):
    class Meta:
        model = SenderId
        fields = ["id", "channel", "name", "purpose", "status", "rejection_reason", "created_at"]
        read_only_fields = fields


class SenderIdCreateSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=["sms", "email"], default="sms")
    name = serializers.CharField(min_length=1, max_length=160)
    purpose = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        name = attrs["name"].strip()
        if attrs["channel"] == "sms":
            if not name.replace(" ", "").isalnum() or len(name) > 11:
                raise serializers.ValidationError(
                    {"name": "An SMS sender ID must be 11 characters or fewer, letters and numbers only."}
                )
        attrs["name"] = name
        return attrs