from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import StaffProfile, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "full_name", "phone", "is_staff", "preferred_language")
    search_fields = ("email", "full_name", "phone")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal", {"fields": ("full_name", "phone", "preferred_language")}),
        ("Verification", {"fields": ("email_verified_at", "phone_verified_at")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "full_name", "phone", "password1", "password2")}),
    )


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "office_phone")
    list_filter = ("title",)
