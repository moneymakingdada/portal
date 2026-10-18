from urllib.parse import quote

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RangeDateTimeFilter, RelatedDropdownFilter
from unfold.decorators import action, display

from .sender_requests import queue_decision_text
from .models import (
    ApiKey, Customer, LedgerEntry, Message, MessageTemplate, Organization, OtpRequest, Payment,
    PricingTier, SenderId, SenderIdDocument, SmsPlan, Suppression, Wallet,
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
    """Review sender ID requests: open the uploaded letter and ID/certificate,
    then approve or reject. Approving only marks it approved on the platform;
    the name must also be registered with the SMS provider before it delivers."""
    list_display = ("name", "organization", "status_badge", "kind", "paperwork", "submitted_at")
    list_filter = (("status", ChoicesDropdownFilter), "is_business")
    list_filter_submit = True
    list_select_related = ("organization",)
    search_fields = ("name", "organization__name", "organization__owner__email")
    ordering = ("-submitted_at",)
    actions_row = ["approve", "reject"]
    fields = ("name", "organization", "status", "rejection_reason", "kind", "purpose",
              "submitted_at", "reviewed_at", "reviewed_by", "document_links")
    readonly_fields = ("organization", "kind", "purpose", "submitted_at", "reviewed_at",
                       "reviewed_by", "document_links")

    @display(description="Status", ordering="status",
             label={"approved": "success", "pending": "warning", "rejected": "danger"})
    def status_badge(self, obj):
        return obj.status

    @display(description="Type", ordering="is_business", label={"Business": "info"})
    def kind(self, obj):
        return "Business" if obj.is_business else "Individual"

    @display(description="Paperwork")
    def paperwork(self, obj):
        kinds = {d.kind for d in obj.documents.all()}
        return " + ".join(label for key, label in (("letter", "Letter"), ("supporting", "ID/certificate")) if key in kinds) or "None"

    @display(description="Uploaded documents")
    def document_links(self, obj):
        if not obj.pk:
            return "-"
        docs = list(obj.documents.defer("data"))
        if not docs:
            return "None uploaded."
        return format_html_join(
            mark_safe("<br>"), '<a href="{}">{}: {}</a> ({} KB)',
            ((reverse("admin:messaging_senderid_document", args=[obj.pk, d.kind]),
              d.get_kind_display(), d.filename, max(1, round(d.size / 1024))) for d in docs),
        )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            Prefetch("documents", queryset=SenderIdDocument.objects.defer("data"))
        )

    def get_urls(self):
        custom = [path(
            "<int:object_id>/document/<str:kind>/",
            self.admin_site.admin_view(self.download_document),
            name="messaging_senderid_document",
        )]
        return custom + super().get_urls()

    def download_document(self, request, object_id, kind):
        if not self.has_view_permission(request):
            raise PermissionDenied
        document = get_object_or_404(SenderIdDocument, sender_id=object_id, kind=kind)
        response = HttpResponse(bytes(document.data), content_type=document.content_type)
        response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(document.filename)}"
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response

    def save_model(self, request, obj, form, change):
        decided = change and "status" in form.changed_data
        if decided:
            obj.reviewed_by, obj.reviewed_at = request.user, timezone.now()
            if obj.status == SenderId.Status.APPROVED:
                obj.rejection_reason = ""
        super().save_model(request, obj, form, change)
        if decided:
            queue_decision_text(obj)

    def _decide(self, request, object_id, status, reason, note):
        sender = SenderId.objects.filter(pk=object_id).first()
        if sender is not None:
            changed = sender.status != status
            sender.status, sender.reviewed_by, sender.reviewed_at = status, request.user, timezone.now()
            sender.rejection_reason = reason
            sender.save(update_fields=["status", "reviewed_by", "reviewed_at", "rejection_reason"])
            if changed:
                queue_decision_text(sender)
            self.message_user(request, note, messages.SUCCESS)
            if status == SenderId.Status.APPROVED and not sender.documents.filter(kind="letter").exists():
                self.message_user(request, "Approved without a letter of authorization on file.", messages.WARNING)
        return redirect(request.META.get("HTTP_REFERER") or reverse("admin:messaging_senderid_changelist"))

    @action(description="Approve", url_path="approve", permissions=["change"])
    def approve(self, request, object_id):
        return self._decide(request, object_id, SenderId.Status.APPROVED, "", "Sender ID approved.")

    @action(description="Reject", url_path="reject", permissions=["change"])
    def reject(self, request, object_id):
        # For a specific reason, edit the request and set the status and reason there instead.
        return self._decide(
            request, object_id, SenderId.Status.REJECTED,
            "We couldn't verify your documents. Please resubmit with a clear, signed letter.",
            "Sender ID rejected.",
        )


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


@admin.register(Suppression)
class SuppressionAdmin(BaseAdmin):
    """Numbers an organization must not message (opt-outs / do-not-contact)."""
    list_display = ("recipient", "organization", "reason", "created_at")
    list_filter = (("organization", RelatedDropdownFilter),)
    list_filter_submit = True
    list_select_related = ("organization",)
    search_fields = ("recipient", "organization__name")


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
