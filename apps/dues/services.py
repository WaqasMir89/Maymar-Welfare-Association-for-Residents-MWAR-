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

from .models import DuesInvoice, DuesPayment, DuesPlan


def _period_bounds(plan: DuesPlan, year: int, month: int) -> tuple[date, date, date]:
    start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = date(year, month, last_day)
    due = date(year, month, min(10, last_day))
    return start, end, due


def _next_dues_receipt() -> str:
    year = timezone.now().year
    prefix = f"DUE-{year}-"
    last = (
        DuesPayment.objects.filter(receipt_number__startswith=prefix)
        .aggregate(m=Max("receipt_number"))
        .get("m")
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:05d}"


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
