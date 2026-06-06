from django.contrib import admin

from .models import Donation, DuesInvoice, DuesPayment, DuesPlan, Expense


@admin.register(DuesPlan)
class DuesPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "amount", "period", "applies_to", "active")


@admin.register(DuesInvoice)
class DuesInvoiceAdmin(admin.ModelAdmin):
    list_display = ("property", "plan", "period_start", "amount_due", "amount_paid", "status")
    list_filter = ("status", "plan")
    date_hierarchy = "period_start"


@admin.register(DuesPayment)
class DuesPaymentAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "invoice", "amount", "method", "paid_at")
    search_fields = ("receipt_number",)


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ("donor_name", "amount", "purpose", "is_public", "donated_at")
    list_filter = ("is_public",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("category", "amount", "status", "incurred_on")
    list_filter = ("status",)
