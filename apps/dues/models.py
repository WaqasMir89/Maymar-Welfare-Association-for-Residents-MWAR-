"""Dues & billing (the RWA financial backbone) plus donations and expenses."""

from __future__ import annotations

import builtins

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.locality.models import Property
from apps.members.models import MemberProfile

PaymentMethod = [
    ("cash", _("Cash")),
    ("bank_transfer", _("Bank transfer")),
    ("jazzcash", _("JazzCash")),
    ("easypaisa", _("EasyPaisa")),
]


class DuesPlan(TimeStampedModel):
    class Period(models.TextChoices):
        MONTHLY = "monthly", _("Monthly")
        QUARTERLY = "quarterly", _("Quarterly")
        ANNUAL = "annual", _("Annual")

    class AppliesTo(models.TextChoices):
        ALL = "all", _("All properties")
        OWNER = "owner", _("Owner-occupied")
        TENANT = "tenant", _("Tenant-occupied")

    name = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    period = models.CharField(max_length=10, choices=Period.choices, default=Period.MONTHLY)
    applies_to = models.CharField(max_length=16, choices=AppliesTo.choices, default=AppliesTo.ALL)
    active = models.BooleanField(default=True)

    class Meta:
        permissions = [
            ("record_payment", "Can record dues/donation payments"),
            ("approve_expense", "Can approve expenses"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.amount} PKR / {self.get_period_display()})"


class DuesInvoice(TimeStampedModel):
    class Status(models.TextChoices):
        UNPAID = "unpaid", _("Unpaid")
        PARTIAL = "partial", _("Partial")
        PAID = "paid", _("Paid")
        WAIVED = "waived", _("Waived")
        OVERDUE = "overdue", _("Overdue")

    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="invoices")
    member = models.ForeignKey(
        MemberProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )
    plan = models.ForeignKey(DuesPlan, on_delete=models.PROTECT, related_name="invoices")
    period_start = models.DateField()
    period_end = models.DateField()
    amount_due = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNPAID)

    class Meta:
        ordering = ["-period_start"]
        indexes = [
            models.Index(fields=["property", "period_start"]),
            models.Index(fields=["status"]),
            models.Index(fields=["due_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["property", "plan", "period_start"], name="uniq_invoice_period"
            )
        ]

    def __str__(self) -> str:
        return f"Invoice {self.property} {self.period_start:%b %Y} — {self.status}"

    # ``property`` field shadows the builtin in this class body.
    @builtins.property
    def balance(self):
        return self.amount_due - self.amount_paid

    def recompute_status(self):
        if self.amount_paid >= self.amount_due:
            self.status = self.Status.PAID
        elif self.amount_paid > 0:
            self.status = self.Status.PARTIAL
        elif self.due_date < timezone.now().date():
            self.status = self.Status.OVERDUE
        else:
            self.status = self.Status.UNPAID


class DuesPayment(TimeStampedModel):
    invoice = models.ForeignKey(DuesInvoice, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=16, choices=PaymentMethod, default="cash")
    reference = models.CharField(max_length=64, blank=True)
    receipt_number = models.CharField(max_length=24, unique=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="received_dues",
    )
    paid_at = models.DateTimeField(default=timezone.now)
    idempotency_key = models.CharField(max_length=64, blank=True, db_index=True)

    def __str__(self) -> str:
        return f"Dues receipt {self.receipt_number}"


class Donation(TimeStampedModel):
    donor_name = models.CharField(max_length=150)
    donor_member = models.ForeignKey(
        MemberProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="donations"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="PKR")
    purpose = models.CharField(max_length=200, blank=True)
    method = models.CharField(max_length=16, choices=PaymentMethod, default="cash")
    reference = models.CharField(max_length=64, blank=True)
    receipt_number = models.CharField(max_length=24, unique=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="received_donations",
    )
    donated_at = models.DateTimeField(default=timezone.now)
    is_public = models.BooleanField(default=False, help_text="Show on the public donor wall (consent).")

    class Meta:
        ordering = ["-donated_at"]

    def __str__(self) -> str:
        return f"{self.donor_name} — {self.amount} {self.currency}"


class Expense(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        PAID = "paid", _("Paid")

    category = models.CharField(max_length=80)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True)
    incurred_on = models.DateField(default=timezone.now)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="requested_expenses",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="approved_expenses",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attachment = models.FileField(upload_to="expense_docs/%Y/%m/", null=True, blank=True)

    class Meta:
        ordering = ["-incurred_on"]

    def __str__(self) -> str:
        return f"{self.category} — {self.amount} ({self.status})"
