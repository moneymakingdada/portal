from django.contrib import admin
from unfold.admin import ModelAdmin as UnfoldModelAdmin
from .models import (
    ApiKey, Customer, LedgerEntry, Message, MessageTemplate, Organization, OtpRequest, Payment,
    PricingTier, SenderId, SmsPlan, Wallet,
)


class ReadOnlyAdmin(UnfoldModelAdmin):
    """For append-only or system-written records: view, never edit."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Organization)
class OrganizationAdmin(UnfoldModelAdmin):
    list_display = ("name", "owner", "is_active", "daily_spend_cap_pesewas", "birthday_messages_enabled", "created_at")
    search_fields = ("name", "owner__email")


@admin.register(SenderId)
class SenderIdAdmin(UnfoldModelAdmin):
    """Approve or reject a sender ID or email display name request here."""
    list_display = ("name", "channel", "organization", "status", "created_at")
    list_filter = ("status", "channel")
    list_editable = ("status",)
    search_fields = ("name", "organization__name")


@admin.register(PricingTier)
class PricingTierAdmin(UnfoldModelAdmin):
    list_display = ("network", "min_monthly_volume", "price_per_segment_pesewas", "otp_price_pesewas")


@admin.register(Wallet)
class WalletAdmin(ReadOnlyAdmin):
    list_display = ("organization", "balance_pesewas", "updated_at")
    search_fields = ("organization__name",)


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "wallet", "kind", "amount_pesewas", "balance_after_pesewas", "note")
    list_filter = ("kind",)
    search_fields = ("wallet__organization__name", "idempotency_key")


@admin.register(Message)
class MessageAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "organization", "recipient", "category", "status", "segments", "cost_pesewas", "provider")
    list_filter = ("status", "category", "provider")
    search_fields = ("recipient", "provider_message_id", "organization__name")


@admin.register(Customer)
class CustomerAdmin(UnfoldModelAdmin):
    list_display = ("name", "phone", "organization", "birthday", "created_at")
    search_fields = ("name", "phone", "organization__name")
    list_filter = ("organization",)


@admin.register(MessageTemplate)
class MessageTemplateAdmin(UnfoldModelAdmin):
    list_display = ("name", "category", "organization", "is_default", "updated_at")
    list_filter = ("category",)
    search_fields = ("name", "organization__name")


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "organization", "provider", "provider_reference", "amount_pesewas", "plan", "status")
    list_filter = ("status", "provider")
    search_fields = ("provider_reference", "organization__name")


@admin.register(SmsPlan)
class SmsPlanAdmin(UnfoldModelAdmin):
    """The plans on the Buy SMS page. Untick is_active to retire one without losing payment history."""
    list_display = ("name", "price_pesewas", "message_count", "is_popular", "is_active", "sort_order")
    list_editable = ("is_popular", "is_active", "sort_order")
    list_filter = ("is_active",)


@admin.register(OtpRequest)
class OtpRequestAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "organization", "recipient", "purpose", "status")
    list_filter = ("status",)


@admin.register(ApiKey)
class ApiKeyAdmin(ReadOnlyAdmin):
    list_display = ("prefix", "name", "organization", "is_live", "created_at", "last_used_at", "revoked_at")