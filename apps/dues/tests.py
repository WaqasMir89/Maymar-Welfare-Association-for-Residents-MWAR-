"""Critical-path tests: dues billing run + idempotent payment recording."""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.dues.models import DuesInvoice, DuesPayment, DuesPlan
from apps.dues.services import generate_invoices, record_dues_payment
from apps.locality.models import Property, Sector, SubSector


class DuesTests(TestCase):
    def setUp(self):
        sector = Sector.objects.create(name="Sector W", code="W")
        sub = SubSector.objects.create(sector=sector, name="Sub 1", code="1")
        for n in range(1, 4):
            Property.objects.create(sub_sector=sub, house_number=str(n))
        self.plan = DuesPlan.objects.create(name="Monthly", amount=Decimal("1500.00"))
        self.user = User.objects.create_user("fin@x.pk", "pw1234567890")

    def test_billing_run_is_idempotent(self):
        first = generate_invoices(self.plan, 2026, 1)
        self.assertEqual(first, 3)                       # one per occupied property
        second = generate_invoices(self.plan, 2026, 1)   # same period again
        self.assertEqual(second, 0)                      # nothing duplicated
        self.assertEqual(DuesInvoice.objects.count(), 3)

    def test_payment_updates_status_and_balance(self):
        generate_invoices(self.plan, 2026, 1)
        inv = DuesInvoice.objects.first()
        record_dues_payment(inv, amount=Decimal("1500.00"), method="cash", user=self.user)
        inv.refresh_from_db()
        self.assertEqual(inv.status, DuesInvoice.Status.PAID)
        self.assertEqual(inv.amount_paid, Decimal("1500.00"))

    def test_partial_payment(self):
        generate_invoices(self.plan, 2026, 1)
        inv = DuesInvoice.objects.first()
        record_dues_payment(inv, amount=Decimal("500.00"), method="cash", user=self.user)
        inv.refresh_from_db()
        self.assertEqual(inv.status, DuesInvoice.Status.PARTIAL)

    def test_idempotency_key_prevents_double_receipt(self):
        generate_invoices(self.plan, 2026, 1)
        inv = DuesInvoice.objects.first()
        p1 = record_dues_payment(inv, amount=Decimal("1500.00"), method="cash",
                                 user=self.user, idempotency_key="abc-123")
        p2 = record_dues_payment(inv, amount=Decimal("1500.00"), method="cash",
                                 user=self.user, idempotency_key="abc-123")
        self.assertEqual(p1.pk, p2.pk)
        self.assertEqual(DuesPayment.objects.count(), 1)
