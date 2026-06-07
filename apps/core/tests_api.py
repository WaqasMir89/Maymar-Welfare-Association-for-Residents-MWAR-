"""API contract tests (doc 04): envelope, JWT, RBAC scoping, PII, idempotency."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from rest_framework.test import APIClient

from django.test import TestCase

from apps.accounts.models import User
from apps.core.models import AuditLog
from apps.dues.models import DuesInvoice, DuesPayment, DuesPlan
from apps.locality.models import Property, Sector, SubSector
from apps.members.models import (
    MemberCard,
    MemberProfile,
    Membership,
    MembershipClass,
)
from apps.tickets.models import Ticket


def _grant(user, codename, app_label):
    perm = Permission.objects.get(codename=codename, content_type__app_label=app_label)
    user.user_permissions.add(perm)


class ApiAuthEnvelopeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("u@x.pk", "password123", full_name="Test User")

    def test_login_returns_enveloped_tokens(self):
        r = self.client.post("/api/v1/auth/login",
                             {"email": "u@x.pk", "password": "password123"}, format="json")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["success"])
        self.assertIn("access", body["data"])

    def test_unauthenticated_error_envelope(self):
        r = self.client.get("/api/v1/members")
        self.assertEqual(r.status_code, 401)
        body = r.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "authentication_required")

    def test_me_reports_roles_and_permissions(self):
        self.client.force_authenticate(self.user)
        r = self.client.get("/api/v1/auth/me")
        body = r.json()
        self.assertEqual(body["data"]["email"], "u@x.pk")
        self.assertIn("roles", body["data"])


class ApiMemberPiiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.profile = MemberProfile.objects.create(
            member_number="MWAR-000001", full_name="Aisha Khan",
            father_or_husband_name="Khan", cnic="42101-1234567-1",
            phone="0300-1234567", status=MemberProfile.Status.ACTIVE,
        )
        self.plain = User.objects.create_user("staff@x.pk", "password123", is_staff=True)
        grp = Group.objects.create(name="Secretary")
        self.plain.groups.add(grp)  # staff but no view_pii

    def test_cnic_masked_without_view_pii(self):
        self.client.force_authenticate(self.plain)
        r = self.client.get("/api/v1/members")
        self.assertEqual(r.json()["data"][0]["cnic"], "*****-*****67-*")

    def test_cnic_unmasked_with_view_pii_is_audited(self):
        _grant(self.plain, "view_pii", "members")
        self.client.force_authenticate(self.plain)
        before = AuditLog.objects.filter(action="pii_access").count()
        r = self.client.get("/api/v1/members")
        self.assertEqual(r.json()["data"][0]["cnic"], "42101-1234567-1")
        self.assertEqual(AuditLog.objects.filter(action="pii_access").count(), before + 1)


class ApiPublicVerifyTests(TestCase):
    def test_public_card_verify_returns_minimal_data(self):
        profile = MemberProfile.objects.create(
            member_number="MWAR-000002", full_name="Bilal Ahmed",
            father_or_husband_name="Ahmed", cnic="42101-7654321-2",
            phone="0300-7654321", status=MemberProfile.Status.ACTIVE,
        )
        card = MemberCard.objects.create(member=profile, member_number="MWAR-000002")
        r = APIClient().get(f"/api/v1/verify/card/{card.qr_token}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["data"]["valid"])
        self.assertEqual(body["data"]["member_number"], "MWAR-000002")
        self.assertNotIn("cnic", body["data"])        # never expose PII


class ApiDuesIdempotencyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        sector = Sector.objects.create(name="Sector W", code="W")
        sub = SubSector.objects.create(sector=sector, name="Sub 1", code="1")
        prop = Property.objects.create(sub_sector=sub, house_number="1")
        plan = DuesPlan.objects.create(name="Monthly", amount=Decimal("1500"))
        self.invoice = DuesInvoice.objects.create(
            property=prop, plan=plan, period_start="2026-01-01", period_end="2026-01-31",
            amount_due=Decimal("1500"), due_date="2026-01-10",
        )
        # is_staff_member() is group-based, so the user must be in a staff group
        # for invoice scoping to expose the invoice (not just the is_staff flag).
        self.finance = User.objects.create_user("fin@x.pk", "password123", is_staff=True)
        self.finance.groups.add(Group.objects.create(name="Finance Officer"))
        _grant(self.finance, "record_payment", "dues")

    def test_idempotency_key_prevents_double_receipt(self):
        self.client.force_authenticate(self.finance)
        url = f"/api/v1/dues/invoices/{self.invoice.id}/payments"
        h = {"HTTP_IDEMPOTENCY_KEY": "key-1"}
        r1 = self.client.post(url, {"amount": "500"}, format="json", **h)
        r2 = self.client.post(url, {"amount": "500"}, format="json", **h)
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r1.json()["data"]["receipt_number"], r2.json()["data"]["receipt_number"])
        self.assertEqual(DuesPayment.objects.count(), 1)

    def test_payment_requires_record_payment_permission(self):
        member = User.objects.create_user("m@x.pk", "password123")
        self.client.force_authenticate(member)
        r = self.client.post(f"/api/v1/dues/invoices/{self.invoice.id}/payments",
                             {"amount": "500"}, format="json")
        self.assertEqual(r.status_code, 403)


class ApiTicketScopingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.a = User.objects.create_user("a@x.pk", "password123")
        self.b = User.objects.create_user("b@x.pk", "password123")
        Ticket.objects.create(title="A's leak", description="x", created_by=self.a)
        Ticket.objects.create(title="B's gate", description="y", created_by=self.b)

    def test_member_sees_only_own_tickets(self):
        self.client.force_authenticate(self.a)
        r = self.client.get("/api/v1/tickets")
        titles = [t["title"] for t in r.json()["data"]]
        self.assertEqual(titles, ["A's leak"])
