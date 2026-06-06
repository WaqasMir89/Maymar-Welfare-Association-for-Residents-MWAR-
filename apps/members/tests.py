"""Critical-path tests: CNIC encryption/masking, two-step approval, PII audit."""

from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from apps.accounts.models import User
from apps.core.crypto import decrypt, encrypt, mask_cnic
from apps.core.models import AuditLog
from apps.locality.models import Property, Sector, SubSector
from apps.members.models import (
    MemberProfile,
    MembershipApplication,
    ResidencyType,
    class_for_residency,
)
from apps.members.services import ApprovalError, chairman_approve, secretary_review, submit_application

CNIC = "42101-1234567-1"


class CryptoTests(TestCase):
    def test_encrypt_roundtrip(self):
        token = encrypt(CNIC)
        self.assertNotIn("42101", token)  # ciphertext doesn't leak the value
        self.assertEqual(decrypt(token), CNIC)

    def test_mask(self):
        self.assertEqual(mask_cnic(CNIC), "*****-*****67-*")

    def test_field_stores_ciphertext(self):
        m = MemberProfile.objects.create(
            full_name="A", father_or_husband_name="B", cnic=CNIC, phone="0301-2345678"
        )
        # Hash is deterministic and set; the model decrypts on read.
        self.assertTrue(m.cnic_hash)
        self.assertEqual(MemberProfile.objects.get(pk=m.pk).cnic, CNIC)


class ApprovalFlowTests(TestCase):
    def setUp(self):
        sector = Sector.objects.create(name="Sector W", code="W")
        sub = SubSector.objects.create(sector=sector, name="Sub 1", code="1")
        self.prop = Property.objects.create(sub_sector=sub, house_number="5")
        self.secretary = User.objects.create_user("sec@x.pk", "pw1234567890", full_name="Sec")
        self.chairman = User.objects.create_user("chair@x.pk", "pw1234567890", full_name="Chair")
        perm = Permission.objects.get(codename="approve_membership")
        self.chairman.user_permissions.add(perm)

    def _make_app(self, residency=ResidencyType.OWNER):
        return MembershipApplication.objects.create(
            full_name="Ali Khan", father_or_husband_name="Ahmed Khan", cnic=CNIC,
            phone="0301-2345678", property=self.prop, residency_type=residency,
            declaration_accepted=True,
        )

    def test_owner_becomes_permanent(self):
        self.assertEqual(class_for_residency(ResidencyType.OWNER), "permanent")
        self.assertEqual(class_for_residency(ResidencyType.TENANT), "associate")

    def test_cannot_skip_secretary(self):
        app = self._make_app()
        submit_application(app)
        with self.assertRaises(ApprovalError):
            chairman_approve(app, self.chairman)

    def test_full_two_step_approval_issues_everything(self):
        app = self._make_app()
        submit_application(app)
        secretary_review(app, self.secretary, decision="approve")
        profile = chairman_approve(app, self.chairman)

        self.assertTrue(profile.member_number.startswith("MWAR-"))
        self.assertEqual(profile.status, MemberProfile.Status.ACTIVE)
        self.assertTrue(profile.fee_payments.exists())          # Rs 500 receipt
        self.assertTrue(hasattr(profile, "card"))               # ID card issued
        self.assertEqual(profile.current_membership.membership_class, "permanent")
        self.assertEqual(profile.current_residency.property, self.prop)

    def test_approval_is_idempotent(self):
        app = self._make_app()
        submit_application(app)
        secretary_review(app, self.secretary, decision="approve")
        first = chairman_approve(app, self.chairman)
        second = chairman_approve(app, self.chairman)  # re-run is a no-op
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(MemberProfile.objects.count(), 1)

    def test_approval_writes_audit_trail(self):
        app = self._make_app()
        submit_application(app)
        secretary_review(app, self.secretary, decision="approve")
        chairman_approve(app, self.chairman)
        self.assertTrue(AuditLog.objects.filter(action="approve").exists())
        self.assertTrue(AuditLog.objects.filter(action="payment").exists())
