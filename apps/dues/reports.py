"""Aggregations for the public transparency page and staff dashboards."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from .models import Donation, DuesInvoice, DuesPayment, Expense


def _money(value) -> Decimal:
    return value or Decimal("0.00")


def transparency_summary() -> dict:
    """Headline figures published openly for residents and donors."""
    dues_collected = DuesPayment.objects.aggregate(s=Sum("amount"))["s"]
    donations = Donation.objects.aggregate(s=Sum("amount"))["s"]
    expenses = Expense.objects.filter(status__in=["approved", "paid"]).aggregate(s=Sum("amount"))["s"]
    billed = DuesInvoice.objects.aggregate(s=Sum("amount_due"))["s"]
    collected = DuesInvoice.objects.aggregate(s=Sum("amount_paid"))["s"]

    total_in = _money(dues_collected) + _money(donations)
    total_out = _money(expenses)
    rate = (_money(collected) / _money(billed) * 100) if billed else Decimal("0")

    return {
        "dues_collected": _money(dues_collected),
        "donations_total": _money(donations),
        "expenses_total": total_out,
        "balance": total_in - total_out,
        "collection_rate": round(rate, 1),
        "public_donations": Donation.objects.filter(is_public=True).order_by("-donated_at")[:10],
        "recent_expenses": Expense.objects.filter(status__in=["approved", "paid"]).order_by("-incurred_on")[:10],
    }
