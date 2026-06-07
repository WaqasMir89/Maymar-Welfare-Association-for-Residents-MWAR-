"""Dues service layer: billing runs and idempotent payment recording."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.services import record_audit
from apps.locality.models import Property
from apps.members.models import ResidencyType

from .models import Donation, DuesInvoice, DuesPayment, DuesPlan, Expense


def _period_bounds(plan: DuesPlan, year: int, month: int) -> tuple[date, date, date]:
    start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = date(year, month, last_day)
    due = date(year, month, min(10, last_day))
    return start, end, due


def _next_receipt(model, field: str, prefix: str) -> str:
    """Next zero-padded receipt number for ``PREFIX-YEAR-#####`` schemes."""
    last = (
        model.objects.filter(**{f"{field}__startswith": prefix})
        .aggregate(m=Max(field))
        .get("m")
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:05d}"


def _next_dues_receipt() -> str:
    return _next_receipt(DuesPayment, "receipt_number", f"DUE-{timezone.now().year}-")


def _next_donation_receipt() -> str:
    return _next_receipt(Donation, "receipt_number", f"DON-{timezone.now().year}-")


@transaction.atomic
def generate_invoices(plan: DuesPlan, year: int, month: int) -> int:
    """Generate one invoice per applicable, occupied property for the period.

    Idempotent through the (property, plan, period_start) unique constraint —
    re-running a period skips properties already billed.
    """
    start, end, due = _period_bounds(plan, year, month)
    properties = Property.objects.filter(status=Property.Status.OCCUPIED)

    created = 0
    for prop in properties.select_related("sub_sector"):
        residency = (
            prop.residencies.filter(is_current=True).select_related("member").first()
        )
        if plan.applies_to == DuesPlan.AppliesTo.OWNER and (
            not residency or residency.residency_type != ResidencyType.OWNER
        ):
            continue
        if plan.applies_to == DuesPlan.AppliesTo.TENANT and (
            not residency or residency.residency_type != ResidencyType.TENANT
        ):
            continue

        _, was_created = DuesInvoice.objects.get_or_create(
            property=prop,
            plan=plan,
            period_start=start,
            defaults={
                "member": residency.member if residency else None,
                "period_end": end,
                "amount_due": plan.amount,
                "due_date": due,
                "status": DuesInvoice.Status.UNPAID,
            },
        )
        created += int(was_created)

    record_audit(AuditLog.Action.CREATE, "DuesInvoice", f"{plan.pk}:{start}",
                 metadata={"plan": plan.name, "period": f"{year}-{month:02d}", "created": created})
    return created


@transaction.atomic
def record_dues_payment(invoice: DuesInvoice, *, amount: Decimal, method: str, user,
                        reference: str = "", idempotency_key: str = "") -> DuesPayment:
    """Record a payment against an invoice and return the receipt.

    Honours an ``Idempotency-Key``: a repeat with the same key returns the
    original receipt instead of double-charging.
    """
    if idempotency_key:
        existing = DuesPayment.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    payment = DuesPayment.objects.create(
        invoice=invoice,
        amount=amount,
        method=method,
        reference=reference,
        receipt_number=_next_dues_receipt(),
        received_by=user,
        idempotency_key=idempotency_key,
    )

    invoice.amount_paid = (invoice.amount_paid or Decimal("0")) + amount
    invoice.recompute_status()
    invoice.save(update_fields=["amount_paid", "status", "updated_at"])

    record_audit(AuditLog.Action.PAYMENT, "DuesPayment", payment.pk, actor=user,
                 metadata={"invoice": invoice.pk, "amount": str(amount),
                           "receipt": payment.receipt_number})
    return payment


@transaction.atomic
def record_donation(*, donor_name: str, amount: Decimal, user, method: str = "cash",
                    purpose: str = "", reference: str = "", donor_member=None,
                    is_public: bool = False) -> Donation:
    """Record a donation and issue a receipt. Audited like any money-in event."""
    donation = Donation.objects.create(
        donor_name=donor_name.strip(),
        donor_member=donor_member,
        amount=amount,
        purpose=purpose.strip(),
        method=method,
        reference=reference.strip(),
        receipt_number=_next_donation_receipt(),
        received_by=user,
        is_public=is_public,
    )
    record_audit(AuditLog.Action.PAYMENT, "Donation", donation.pk, actor=user,
                 metadata={"amount": str(amount), "receipt": donation.receipt_number,
                           "public": is_public})
    return donation


@transaction.atomic
def create_expense(*, category: str, amount: Decimal, user, description: str = "",
                   incurred_on=None, attachment=None) -> Expense:
    """Raise an expense request (status ``pending`` until approved)."""
    expense = Expense.objects.create(
        category=category.strip(),
        amount=amount,
        description=description.strip(),
        incurred_on=incurred_on or timezone.now().date(),
        requested_by=user,
        attachment=attachment,
        status=Expense.Status.PENDING,
    )
    record_audit(AuditLog.Action.CREATE, "Expense", expense.pk, actor=user,
                 metadata={"category": expense.category, "amount": str(amount)})
    return expense


@transaction.atomic
def decide_expense(expense: Expense, *, approve: bool, user) -> Expense:
    """Approve or reject a pending expense. Idempotent once decided."""
    if expense.status != Expense.Status.PENDING:
        return expense
    expense.status = Expense.Status.APPROVED if approve else Expense.Status.REJECTED
    expense.approved_by = user
    expense.save(update_fields=["status", "approved_by", "updated_at"])
    record_audit(AuditLog.Action.UPDATE, "Expense", expense.pk, actor=user,
                 metadata={"decision": expense.status, "amount": str(expense.amount)})
    return expense
