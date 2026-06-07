"""Critical-path tests: dues billing run + idempotent payment recording."""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.core.models import AuditLog
from apps.dues.models import Donation, DuesInvoice, DuesPayment, DuesPlan, Expense
from apps.dues.services import (
    create_expense,
    decide_expense,
    generate_invoices,
    record_donation,
    record_dues_payment,
)
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


class DonationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("fin@x.pk", "pw1234567890")

    def test_donation_issues_receipt_and_audits(self):
        before = AuditLog.objects.filter(action=AuditLog.Action.PAYMENT).count()
        d = record_donation(donor_name="  Abdul Karim  ", amount=Decimal("5000"),
                            user=self.user, purpose="Ramzan", is_public=True)
        self.assertEqual(d.donor_name, "Abdul Karim")        # trimmed
        self.assertTrue(d.receipt_number.startswith("DON-"))
        self.assertEqual(
            AuditLog.objects.filter(action=AuditLog.Action.PAYMENT).count(), before + 1
        )

    def test_receipt_numbers_increment(self):
        a = record_donation(donor_name="A", amount=Decimal("100"), user=self.user)
        b = record_donation(donor_name="B", amount=Decimal("100"), user=self.user)
        self.assertNotEqual(a.receipt_number, b.receipt_number)
        self.assertEqual(Donation.objects.count(), 2)


class ExpenseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("fin@x.pk", "pw1234567890")

    def test_expense_starts_pending_then_approves(self):
        e = create_expense(category=" Security ", amount=Decimal("12000"), user=self.user)
        self.assertEqual(e.category, "Security")
        self.assertEqual(e.status, Expense.Status.PENDING)
        decide_expense(e, approve=True, user=self.user)
        e.refresh_from_db()
        self.assertEqual(e.status, Expense.Status.APPROVED)
        self.assertEqual(e.approved_by, self.user)

    def test_decision_is_idempotent_once_decided(self):
        e = create_expense(category="Lighting", amount=Decimal("3000"), user=self.user)
        decide_expense(e, approve=False, user=self.user)          # rejected
        decide_expense(e, approve=True, user=self.user)           # ignored
        e.refresh_from_db()
        self.assertEqual(e.status, Expense.Status.REJECTED)
