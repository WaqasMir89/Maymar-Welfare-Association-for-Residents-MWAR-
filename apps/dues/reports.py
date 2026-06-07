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


def transaction_ledger(*, kind=None, direction=None, start=None, end=None, search=""):
    """A flat, chronological ledger of every individual money movement —
    dues payments, registration fees, donations (in) and expenses (out).

    Returns a list of dicts sorted newest-first. Filters narrow by kind,
    direction (in/out), date range and a free-text search.
    """
    from apps.members.models import FeePayment

    s = (search or "").strip().lower()
    rows: list[dict] = []

    def _match(*fields) -> bool:
        return not s or any(s in (f or "").lower() for f in fields)

    want_in = direction in (None, "", "in")
    want_out = direction in (None, "", "out")

    if want_in and kind in (None, "", "dues"):
        qs = DuesPayment.objects.select_related(
            "invoice__member", "invoice__property", "received_by")
        if start:
            qs = qs.filter(paid_at__date__gte=start)
        if end:
            qs = qs.filter(paid_at__date__lte=end)
        for p in qs:
            member = p.invoice.member.full_name if p.invoice and p.invoice.member else ""
            prop = str(p.invoice.property) if p.invoice and p.invoice.property_id else ""
            if not _match(member, prop, p.reference, p.receipt_number):
                continue
            rows.append({
                "date": p.paid_at, "kind": "dues", "kind_label": "Dues payment",
                "direction": "in", "party": member or prop or "—", "detail": prop,
                "amount": p.amount, "method": p.get_method_display(),
                "reference": p.reference, "receipt": p.receipt_number,
                "recorded_by": p.received_by, "pdf": ("dues:dues_receipt_pdf", p.pk),
            })

    if want_in and kind in (None, "", "fee"):
        qs = FeePayment.objects.select_related("member", "received_by")
        if start:
            qs = qs.filter(paid_at__date__gte=start)
        if end:
            qs = qs.filter(paid_at__date__lte=end)
        for f in qs:
            member = f.member.full_name if f.member else ""
            if not _match(member, f.reference, f.receipt_number):
                continue
            rows.append({
                "date": f.paid_at, "kind": "fee", "kind_label": "Registration fee",
                "direction": "in", "party": member or "—", "detail": "Membership registration",
                "amount": f.amount, "method": f.get_method_display(),
                "reference": f.reference, "receipt": f.receipt_number,
                "recorded_by": f.received_by, "pdf": ("members:fee_receipt_pdf", f.pk),
            })

    if want_in and kind in (None, "", "donation"):
        qs = Donation.objects.select_related("received_by")
        if start:
            qs = qs.filter(donated_at__date__gte=start)
        if end:
            qs = qs.filter(donated_at__date__lte=end)
        for d in qs:
            if not _match(d.donor_name, d.purpose, d.reference, d.receipt_number):
                continue
            rows.append({
                "date": d.donated_at, "kind": "donation", "kind_label": "Donation",
                "direction": "in", "party": d.donor_name, "detail": d.purpose,
                "amount": d.amount, "method": d.get_method_display(),
                "reference": d.reference, "receipt": d.receipt_number,
                "recorded_by": d.received_by, "pdf": ("dues:donation_receipt_pdf", d.pk),
            })

    if want_out and kind in (None, "", "expense"):
        qs = Expense.objects.filter(status__in=["approved", "paid"]).select_related(
            "approved_by", "requested_by")
        if start:
            qs = qs.filter(incurred_on__gte=start)
        if end:
            qs = qs.filter(incurred_on__lte=end)
        for e in qs:
            if not _match(e.category, e.description):
                continue
            rows.append({
                "date": e.incurred_on, "kind": "expense", "kind_label": "Expense",
                "direction": "out", "party": e.category, "detail": e.description,
                "amount": e.amount, "method": e.get_status_display(),
                "reference": "", "receipt": "",
                "recorded_by": e.approved_by or e.requested_by, "pdf": None,
            })

    def _sort_key(r):
        d = r["date"]
        return d if hasattr(d, "timestamp") else timezone.make_aware(
            timezone.datetime.combine(d, timezone.datetime.min.time()))

    rows.sort(key=_sort_key, reverse=True)
    return rows


def ledger_totals(rows) -> dict:
    total_in = sum((r["amount"] for r in rows if r["direction"] == "in"), Decimal("0"))
    total_out = sum((r["amount"] for r in rows if r["direction"] == "out"), Decimal("0"))
    return {"total_in": total_in, "total_out": total_out, "net": total_in - total_out,
            "count": len(rows)}


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
