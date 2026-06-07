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


class PaymentSubmissionTests(TestCase):
    """Member 'pay in one click' with proof, then Finance verification posts
    the real receipts to the ledger."""

    def setUp(self):
        from datetime import date

        from django.contrib.auth.models import Permission

        from apps.members.models import MemberProfile

        sector = Sector.objects.create(name="Sector W", code="W")
        sub = SubSector.objects.create(sector=sector, name="Sub 1", code="1")
        self.prop = Property.objects.create(sub_sector=sub, house_number="7",
                                            status=Property.Status.OCCUPIED)
        self.plan = DuesPlan.objects.create(name="Monthly", amount=Decimal("1500.00"))
        self.member_user = User.objects.create_user("member@x.pk", "pw1234567890")
        self.profile = MemberProfile.objects.create(
            full_name="Ali Khan", father_or_husband_name="X", cnic="42101-9999999-9",
            phone="0300-9999999", status=MemberProfile.Status.ACTIVE, user=self.member_user,
        )
        self.invoice = DuesInvoice.objects.create(
            property=self.prop, member=self.profile, plan=self.plan,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            amount_due=Decimal("1500.00"), due_date=date(2026, 1, 10),
            status=DuesInvoice.Status.UNPAID,
        )
        self.finance = User.objects.create_user("fin@x.pk", "pw1234567890")
        self.finance.user_permissions.add(
            Permission.objects.get(codename="record_payment", content_type__app_label="dues")
        )

    def _proof(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile("slip.jpg", b"\xff\xd8\xff data", content_type="image/jpeg")

    def test_member_submits_then_finance_verifies_posts_ledger(self):
        self.client.force_login(self.member_user)
        r = self.client.post("/dues/pay/", {
            "method": "bank_transfer", "reference": "TX99", "donation_amount": "500",
            "proof": self._proof(),
        })
        self.assertRedirects(r, "/dues/my-dues/")
        from apps.dues.models import PaymentSubmission

        sub = PaymentSubmission.objects.get(member=self.profile)
        self.assertEqual(sub.status, "pending")
        self.assertEqual(sub.dues_amount, Decimal("1500.00"))
        self.assertEqual(sub.donation_amount, Decimal("500"))
        self.assertEqual(sub.total_amount, Decimal("2000.00"))

        # Finance verifies → invoice paid, dues payment + donation created.
        self.client.force_login(self.finance)
        r = self.client.post(f"/dues/staff/submissions/{sub.pk}/decide/", {"decision": "verify"})
        sub.refresh_from_db(); self.invoice.refresh_from_db()
        self.assertEqual(sub.status, "verified")
        self.assertEqual(self.invoice.status, "paid")
        self.assertEqual(DuesPayment.objects.filter(invoice=self.invoice).count(), 1)
        self.assertEqual(Donation.objects.filter(donor_member=self.profile).count(), 1)

    def test_verify_is_idempotent(self):
        from apps.dues.services import create_payment_submission, verify_payment_submission
        from apps.dues.models import PaymentSubmission

        sub = create_payment_submission(
            member=self.profile, user=self.member_user, invoices=[self.invoice],
            donation_amount=Decimal("0"), method="bank_transfer", proof=self._proof(),
        )
        verify_payment_submission(sub, user=self.finance)
        verify_payment_submission(sub, user=self.finance)   # no double-post
        self.assertEqual(DuesPayment.objects.filter(invoice=self.invoice).count(), 1)

    def test_submission_requires_proof(self):
        self.client.force_login(self.member_user)
        r = self.client.post("/dues/pay/", {"method": "bank_transfer", "donation_amount": "0"})
        self.assertRedirects(r, "/dues/pay/")
        from apps.dues.models import PaymentSubmission

        self.assertEqual(PaymentSubmission.objects.count(), 0)

    def test_proof_visible_to_owner_and_staff_only(self):
        from apps.dues.services import create_payment_submission

        sub = create_payment_submission(
            member=self.profile, user=self.member_user, invoices=[self.invoice],
            method="bank_transfer", proof=self._proof(),
        )
        url = f"/dues/proof/{sub.pk}/"
        self.client.force_login(self.member_user)
        self.assertEqual(self.client.get(url).status_code, 200)      # owner
        self.client.force_login(self.finance)
        self.assertEqual(self.client.get(url).status_code, 200)      # staff
        stranger = User.objects.create_user("x@x.pk", "pw1234567890")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(url).status_code, 403)


class ReportsAndExportsTests(TestCase):
    """Month-wise breakdown maths + CSV report downloads with access control."""

    def setUp(self):
        from datetime import date

        from django.contrib.auth.models import Group, Permission

        sector = Sector.objects.create(name="Sector W", code="W")
        sub = SubSector.objects.create(sector=sector, name="Sub 1", code="1")
        self.prop = Property.objects.create(sub_sector=sub, house_number="3",
                                            status=Property.Status.OCCUPIED)
        self.plan = DuesPlan.objects.create(name="Monthly", amount=Decimal("1500.00"))
        self.finance = User.objects.create_user("fin@x.pk", "pw1234567890")
        self.finance.groups.add(Group.objects.create(name="Finance Officer"))
        self.finance.user_permissions.add(
            Permission.objects.get(codename="record_payment", content_type__app_label="dues")
        )
        # One unpaid invoice (arrears) + one payment + one expense this month.
        self.invoice = DuesInvoice.objects.create(
            property=self.prop, plan=self.plan, period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31), amount_due=Decimal("1500.00"),
            due_date=date(2026, 1, 10), status=DuesInvoice.Status.UNPAID,
        )
        paid = DuesInvoice.objects.create(
            property=self.prop, plan=self.plan, period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28), amount_due=Decimal("1500.00"),
            due_date=date(2026, 2, 10), status=DuesInvoice.Status.UNPAID,
        )
        record_dues_payment(paid, amount=Decimal("1500"), method="cash", user=self.finance)
        create_expense(category="Security", amount=Decimal("500"), user=self.finance)
        Expense.objects.update(status=Expense.Status.PAID)

    def test_monthly_breakdown_buckets_in_and_out(self):
        from apps.dues.reports import monthly_breakdown

        rows = monthly_breakdown(12)
        self.assertEqual(len(rows), 12)
        totals_in = sum(r["collected"] for r in rows)
        totals_out = sum(r["spent"] for r in rows)
        self.assertEqual(totals_in, Decimal("1500"))
        self.assertEqual(totals_out, Decimal("500"))

    def test_pending_dues_csv_lists_only_outstanding(self):
        self.client.force_login(self.finance)
        r = self.client.get("/dues/staff/reports/pending-dues.csv")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"].split(";")[0], "text/csv")
        body = r.content.decode("utf-8")
        self.assertIn("Balance", body)            # header present
        self.assertEqual(body.count("\r\n"), 2)   # header + 1 unpaid invoice row

    def test_public_finance_csv_is_open_and_pii_free(self):
        r = self.client.get("/dues/reports/collection-and-spending.csv")   # anonymous
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8")
        self.assertIn("Collected (PKR)", body)
        self.assertNotIn("Member", body)

    def test_staff_reports_require_staff(self):
        # Anonymous is redirected to login by the staff gate.
        self.assertEqual(
            self.client.get("/dues/staff/reports/pending-dues.csv").status_code, 302
        )
        self.assertEqual(self.client.get("/complaints/export.csv").status_code, 302)

    def test_finance_dashboard_renders(self):
        self.client.force_login(self.finance)
        r = self.client.get("/dues/staff/dashboard/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Month-wise collection vs spending")


class TransactionLedgerTests(TestCase):
    """The line-by-line ledger merges every money movement and filters it."""

    def setUp(self):
        from datetime import date

        from django.contrib.auth.models import Group, Permission

        sector = Sector.objects.create(name="Sector W", code="W")
        sub = SubSector.objects.create(sector=sector, name="Sub 1", code="1")
        self.prop = Property.objects.create(sub_sector=sub, house_number="4",
                                            status=Property.Status.OCCUPIED)
        self.plan = DuesPlan.objects.create(name="Monthly", amount=Decimal("1500.00"))
        self.finance = User.objects.create_user("fin@x.pk", "pw1234567890", full_name="Fin")
        self.finance.groups.add(Group.objects.create(name="Finance Officer"))
        self.finance.user_permissions.add(
            Permission.objects.get(codename="record_payment", content_type__app_label="dues")
        )
        inv = DuesInvoice.objects.create(
            property=self.prop, plan=self.plan, period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31), amount_due=Decimal("1500.00"),
            due_date=date(2026, 1, 10), status=DuesInvoice.Status.UNPAID,
        )
        record_dues_payment(inv, amount=Decimal("1500"), method="cash", user=self.finance)
        record_donation(donor_name="Abdul Karim", amount=Decimal("5000"),
                        user=self.finance, purpose="Ramzan drive")
        e = create_expense(category="Security", amount=Decimal("2000"), user=self.finance)
        e.status = Expense.Status.PAID
        e.save()

    def test_ledger_merges_all_kinds_with_directions(self):
        from apps.dues.reports import ledger_totals, transaction_ledger

        rows = transaction_ledger()
        kinds = {r["kind"] for r in rows}
        self.assertEqual(kinds, {"dues", "donation", "expense"})
        totals = ledger_totals(rows)
        self.assertEqual(totals["total_in"], Decimal("6500"))   # 1500 dues + 5000 donation
        self.assertEqual(totals["total_out"], Decimal("2000"))  # expense
        self.assertEqual(totals["net"], Decimal("4500"))

    def test_filters_by_kind_direction_and_search(self):
        from apps.dues.reports import transaction_ledger

        self.assertEqual(len(transaction_ledger(kind="expense")), 1)
        self.assertEqual(len(transaction_ledger(direction="in")), 2)
        self.assertEqual(len(transaction_ledger(direction="out")), 1)
        self.assertEqual(len(transaction_ledger(search="Karim")), 1)
        self.assertEqual(len(transaction_ledger(search="nomatch")), 0)

    def test_ledger_page_and_csv_require_staff(self):
        self.assertEqual(self.client.get("/dues/staff/transactions/").status_code, 302)
        self.client.force_login(self.finance)
        r = self.client.get("/dues/staff/transactions/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Transaction Ledger")
        self.assertContains(r, "Abdul Karim")
        csv = self.client.get("/dues/staff/transactions.csv")
        self.assertEqual(csv["Content-Type"].split(";")[0], "text/csv")
        body = csv.content.decode("utf-8")
        self.assertIn("Money in", body)
        self.assertIn("Abdul Karim", body)
