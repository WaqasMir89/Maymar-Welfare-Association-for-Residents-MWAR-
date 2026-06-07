"""Aggregations for the public transparency page and staff dashboards."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Donation, DuesInvoice, DuesPayment, Expense

MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _money(value) -> Decimal:
    return value or Decimal("0.00")


def _month_series(months: int) -> list[tuple[int, int]]:
    """The trailing ``months`` (year, month) pairs, oldest first."""
    today = timezone.now().date()
    y, m = today.year, today.month
    series = []
    for _ in range(months):
        series.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(series))


def _monthly_sums(qs, date_field: str) -> dict[tuple[int, int], Decimal]:
    rows = qs.annotate(mo=TruncMonth(date_field)).values("mo").annotate(s=Sum("amount"))
    return {(r["mo"].year, r["mo"].month): _money(r["s"]) for r in rows if r["mo"]}


def monthly_breakdown(months: int = 12) -> list[dict]:
    """Month-by-month money in (dues + donations) vs money out (expenses)."""
    series = _month_series(months)
    start = date(series[0][0], series[0][1], 1)

    dues = _monthly_sums(DuesPayment.objects.filter(paid_at__date__gte=start), "paid_at")
    donations = _monthly_sums(Donation.objects.filter(donated_at__date__gte=start), "donated_at")
    expenses = _monthly_sums(
        Expense.objects.filter(status__in=["approved", "paid"], incurred_on__gte=start),
        "incurred_on",
    )

    out = []
    for (y, m) in series:
        d, g = dues.get((y, m), Decimal("0")), donations.get((y, m), Decimal("0"))
        e = expenses.get((y, m), Decimal("0"))
        collected = d + g
        out.append({
            "year": y, "month": m, "label": f"{MONTH_NAMES[m]} {y}",
            "dues": d, "donations": g, "collected": collected,
            "spent": e, "net": collected - e,
        })
    return out


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


def finance_dashboard(months: int = 12) -> dict:
    """Everything the staff finance dashboard needs in one call."""
    summary = transparency_summary()
    monthly = monthly_breakdown(months)

    # A scale for the inline bar chart (largest in/out across the window).
    peak = max([Decimal("0")] + [max(r["collected"], r["spent"]) for r in monthly])

    arrears = DuesInvoice.objects.filter(status__in=["unpaid", "partial", "overdue"])
    arrears_total = sum((inv.balance for inv in arrears), Decimal("0"))

    expense_categories = list(
        Expense.objects.filter(status__in=["approved", "paid"])
        .values("category").annotate(total=Sum("amount")).order_by("-total")[:8]
    )

    return {
        **summary,
        "monthly": monthly,
        "peak": peak,
        "arrears_count": arrears.count(),
        "arrears_total": arrears_total,
        "expense_categories": expense_categories,
    }
