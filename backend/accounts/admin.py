from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin
from unfold.decorators import display
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import User


class AdminUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "full_name")


class AdminUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    change_password_form = AdminPasswordChangeForm
    ordering = ("-date_joined",)
    list_display = ("email", "full_name", "phone", "phone_verified", "role", "is_active", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser")
    list_filter_submit = True
    search_fields = ("email", "full_name", "phone")
    compressed_fields = True
    warn_unsaved_form = True
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "phone", "phone_verified_at")}),
        ("Terms", {"fields": ("terms_accepted_at", "terms_version")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "full_name", "password1", "password2")}),
    )

    @display(description="Phone verified", boolean=True)
    def phone_verified(self, obj):
        return obj.phone_verified_at is not None

    @display(description="Role", label={"Superuser": "danger", "Staff": "info", "Customer": "success"})
    def role(self, obj):
        if obj.is_superuser:
            return "Superuser"
        return "Staff" if obj.is_staff else "Customer"


# Groups ship with Django's plain admin; re-register them so they match.
admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass
