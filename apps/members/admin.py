from django.contrib import admin

from .models import (
    ApplicationDocument,
    FeePayment,
    MemberCard,
    MemberProfile,
    Membership,
    MembershipApplication,
    Residency,
)


class ResidencyInline(admin.TabularInline):
    model = Residency
    extra = 0


@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):
    list_display = ("member_number", "full_name", "masked_cnic", "status", "phone")
    list_filter = ("status",)
    search_fields = ("member_number", "full_name", "phone")
    readonly_fields = ("cnic_hash", "masked_cnic")
    inlines = [ResidencyInline]
    exclude = ("cnic",)  # never edit raw CNIC through admin


class DocumentInline(admin.TabularInline):
    model = ApplicationDocument
    extra = 0


@admin.register(MembershipApplication)
class MembershipApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "residency_type", "status", "created_at")
    list_filter = ("status", "residency_type")
    search_fields = ("full_name", "phone")
    inlines = [DocumentInline]
    exclude = ("cnic",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("member", "membership_class", "status", "approved_at")
    list_filter = ("membership_class", "status")


@admin.register(MemberCard)
class MemberCardAdmin(admin.ModelAdmin):
    list_display = ("member_number", "status", "issued_at")


@admin.register(FeePayment)
class FeePaymentAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "member", "amount", "method", "paid_at")
    search_fields = ("receipt_number",)
