from django import forms
from django.contrib import admin, messages
from unfold.admin import ModelAdmin
from unfold.decorators import display

from .models import Conversation, Ticket, Turn
from .tickets import reply_to_ticket


class TurnInline(admin.TabularInline):
    model = Turn
    extra = 0
    can_delete = False
    fields = ("created_at", "role", "text", "tools_used")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Ticket)
class TicketAdmin(ModelAdmin):
    list_display = ("ref", "subject", "organization", "state", "created_at")
    list_filter = ("status",)
    search_fields = ("subject", "details", "organization__name", "user__email")
    list_per_page = 50
    readonly_fields = ("organization", "user", "conversation", "subject", "details", "created_at",
                       "replied_at", "replied_by", "reply_texted")
    fields = ("organization", "user", "created_at", "subject", "details", "conversation",
              "status", "staff_reply", "replied_at", "replied_by", "reply_texted")
    list_select_related = ("organization",)

    @display(description="Ticket")
    def ref(self, obj):
        return f"#{obj.pk}"

    @display(description="Status", label={"open": "warning", "answered": "success", "closed": "info"})
    def state(self, obj):
        return obj.status, obj.get_status_display()

    def has_add_permission(self, request):
        return False        # tickets come from customers

    def save_model(self, request, obj, form, change):
        new_reply = "staff_reply" in form.changed_data and obj.staff_reply.strip()
        if not new_reply:
            return super().save_model(request, obj, form, change)
        texted = reply_to_ticket(obj, request.user, obj.staff_reply)
        if texted:
            messages.success(request, "Reply saved and texted to the customer.")
        else:
            messages.warning(request, "Reply saved and visible on their Support page, but the text message "
                                      "couldn't be sent (no phone number, or the SMS failed).")


@admin.register(Conversation)
class ConversationAdmin(ModelAdmin):
    list_display = ("id", "organization", "user", "updated_at")
    search_fields = ("organization__name", "user__email")
    readonly_fields = ("organization", "user", "created_at", "updated_at")
    inlines = [TurnInline]
    list_per_page = 50

    def has_add_permission(self, request):
        return False
