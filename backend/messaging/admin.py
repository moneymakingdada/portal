from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RangeDateTimeFilter, RelatedDropdownFilter
from unfold.decorators import action, display

from .models import (
    ApiKey, Customer, LedgerEntry, Message, MessageTemplate, Organization, OtpRequest, Payment,
    PricingTier, SenderId, SmsPlan, Wallet,
)


def ghs(pesewas) -> str:
    """Integer pesewas -> 'GHS 12.50' (the database only ever holds pesewas)."""
    if pesewas is None:
        return "-"
    return f"GHS {pesewas / 100:,.2f}"


class BaseAdmin(ModelAdmin):
    warn_unsaved_form = True
    list_per_page = 50


class ReadOnlyAdmin(BaseAdmin):
    """For append-only or system-written records: view, never edit."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Organization)
class OrganizationAdmin(BaseAdmin):
    list_display = ("name", "owner", "status", "wallet_balance", "daily_spend_cap", "birthday_messages_enabled", "created_at")
    list_filter = ("is_active", "birthday_messages_enabled")
    list_filter_submit = True
    list_select_related = ("owner", "wallet")
    search_fields = ("name", "owner__email")
    actions = ["suspend", "reactivate"]

    @display(description="Status", ordering="is_active", label={"Active": "success", "Suspended": "danger"})
    def status(self, obj):
        return "Active" if obj.is_active else "Suspended"

    @display(description="Wallet")
    def wallet_balance(self, obj):
        wallet = getattr(obj, "wallet", None)
        return ghs(wallet.balance_pesewas) if wallet else "-"

    @display(description="Daily spend cap", ordering="daily_spend_cap_pesewas")
    def daily_spend_cap(self, obj):
        return ghs(obj.daily_spend_cap_pesewas)

    @admin.action(description="Suspend selected organizations (API keys stop working)")
    def suspend(self, request, queryset):
        self.message_user(request, f"Suspended {queryset.update(is_active=False)} organization(s).", messages.WARNING)

    @admin.action(description="Reactivate selected organizations")
    def reactivate(self, request, queryset):
        self.message_user(request, f"Reactivated {queryset.update(is_active=True)} organization(s).", messages.SUCCESS)


@admin.register(SenderId)
class SenderIdAdmin(BaseAdmin):
    """Approve or reject sender IDs here after the telco decides."""
    list_display = ("name", "organization", "status_badge", "purpose", "created_at")
    list_filter = (("status", ChoicesDropdownFilter),)
    list_filter_submit = True
    list_select_related = ("organization",)
    search_fields = ("name", "organization__name")
    actions_row = ["approve", "reject"]

    @display(description="Status", ordering="status",
             label={"approved": "success", "pending": "warning", "rejected": "danger"})
    def status_badge(self, obj):
        return obj.status

    def _set_status(self, request, object_id, status, note):
        updated = SenderId.objects.filter(pk=object_id).update(
            status=status, rejection_reason="" if status == SenderId.Status.APPROVED else "Rejected by admin"
        )
        if updated:
            self.message_user(request, note, messages.SUCCESS)
        return redirect(request.META.get("HTTP_REFERER") or reverse("admin:messaging_senderid_changelist"))

    @action(description="Approve", url_path="approve", permissions=["change"])
    def approve(self, request, object_id):
        return self._set_status(request, object_id, SenderId.Status.APPROVED, "Sender ID approved.")

    @action(description="Reject", url_path="reject", permissions=["change"])
    def reject(self, request, object_id):
        return self._set_status(request, object_id, SenderId.Status.REJECTED, "Sender ID rejected.")


@admin.register(PricingTier)
class PricingTierAdmin(BaseAdmin):
    list_display = ("network", "min_monthly_volume", "per_segment", "otp_price")

    @display(description="Per segment", ordering="price_per_segment_pesewas")
    def per_segment(self, obj):
        return ghs(obj.price_per_segment_pesewas)

    @display(description="OTP price", ordering="otp_price_pesewas")
    def otp_price(self, obj):
        return ghs(obj.otp_price_pesewas)


@admin.register(Wallet)
class WalletAdmin(ReadOnlyAdmin):
    list_display = ("organization", "balance", "updated_at")
    list_select_related = ("organization",)
    search_fields = ("organization__name",)

    @display(description="Balance", ordering="balance_pesewas")
    def balance(self, obj):
        return ghs(obj.balance_pesewas)


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "wallet", "kind_badge", "amount", "balance_after", "note")
    list_filter = (("kind", ChoicesDropdownFilter), ("created_at", RangeDateTimeFilter))
    list_filter_submit = True
    list_select_related = ("wallet__organization",)
    search_fields = ("wallet__organization__name", "idempotency_key")

    @display(description="Kind", ordering="kind",
             label={"topup": "success", "debit": "info", "refund": "warning", "adjustment": "danger"})
    def kind_badge(self, obj):
        return obj.kind

    @display(description="Amount", ordering="amount_pesewas")
    def amount(self, obj):
        return ghs(obj.amount_pesewas)

    @display(description="Balance after", ordering="balance_after_pesewas")
    def balance_after(self, obj):
        return ghs(obj.balance_after_pesewas)


@admin.register(Message)
class MessageAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "organization", "recipient", "category", "status_badge", "segments", "cost", "provider")
    list_filter = (
        ("status", ChoicesDropdownFilter),
        ("category", ChoicesDropdownFilter),
        ("provider", ChoicesDropdownFilter),
        ("created_at", RangeDateTimeFilter),
    )
    list_filter_submit = True
    list_select_related = ("organization",)
    search_fields = ("recipient", "provider_message_id", "organization__name")

    @display(description="Status", ordering="status", label={
        "delivered": "success", "sent": "info", "queued": "warning", "failed": "danger", "expired": "danger",
    })
    def status_badge(self, obj):
        return obj.status

    @display(description="Cost", ordering="cost_pesewas")
    def cost(self, obj):
        return ghs(obj.cost_pesewas)


@admin.register(Customer)
class CustomerAdmin(BaseAdmin):
    list_display = ("name", "phone", "organization", "birthday", "created_at")
    search_fields = ("name", "phone", "organization__name")
    list_filter = (("organization", RelatedDropdownFilter),)
    list_filter_submit = True
    list_select_related = ("organization",)


@admin.register(MessageTemplate)
class MessageTemplateAdmin(BaseAdmin):
    list_display = ("name", "category", "organization", "is_default", "updated_at")
    list_filter = (("category", ChoicesDropdownFilter),)
    list_filter_submit = True
    list_select_related = ("organization",)
    search_fields = ("name", "organization__name")


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "organization", "provider", "provider_reference", "amount", "plan", "status_badge")
    list_filter = (("status", ChoicesDropdownFilter), ("provider", ChoicesDropdownFilter), ("created_at", RangeDateTimeFilter))
    list_filter_submit = True
    list_select_related = ("organization", "plan")
    search_fields = ("provider_reference", "organization__name")

    @display(description="Status", ordering="status",
             label={"success": "success", "pending": "warning", "failed": "danger"})
    def status_badge(self, obj):
        return obj.status

    @display(description="Amount", ordering="amount_pesewas")
    def amount(self, obj):
        return ghs(obj.amount_pesewas)


@admin.register(SmsPlan)
class SmsPlanAdmin(BaseAdmin):
    """The plans on the Buy SMS page. Untick is_active to retire one without losing payment history."""
    list_display = ("name", "price", "message_count", "is_popular", "is_active", "sort_order")
    list_editable = ("is_popular", "is_active", "sort_order")
    list_filter = ("is_active",)

    @display(description="Price", ordering="price_pesewas")
    def price(self, obj):
        return ghs(obj.price_pesewas)


@admin.register(OtpRequest)
class OtpRequestAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "organization", "recipient", "purpose", "status_badge")
    list_filter = (("status", ChoicesDropdownFilter), ("created_at", RangeDateTimeFilter))
    list_filter_submit = True
    list_select_related = ("organization",)

    @display(description="Status", ordering="status", label={
        "verified": "success", "pending": "warning", "expired": "info", "locked": "danger", "cancelled": "info",
    })
    def status_badge(self, obj):
        return obj.status


@admin.register(ApiKey)
class ApiKeyAdmin(ReadOnlyAdmin):
    list_display = ("prefix", "name", "organization", "mode", "created_at", "last_used_at", "revoked")
    list_select_related = ("organization",)

    @display(description="Mode", ordering="is_live", label={"Live": "success", "Test": "info"})
    def mode(self, obj):
        return "Live" if obj.is_live else "Test"

    @display(description="Revoked", boolean=True, ordering="revoked_at")
    def revoked(self, obj):
        return obj.revoked_at is not None
