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
from apps.members.services import (
    ApprovalError,
    chairman_approve,
    open_application_for,
    secretary_review,
    submit_application,
)

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


class PdfTests(TestCase):
    """The branded receipt/card generators produce valid, glyph-safe PDFs."""

    def test_clean_strips_urdu_and_tidies_parens(self):
        from apps.core.pdf import _clean

        # The membership-class label carries Urdu the built-in font can't draw.
        self.assertEqual(_clean("Permanent Member (مستقل ممبر)"), "Permanent Member")
        self.assertEqual(_clean("Owner (مالک)"), "Owner")

    def test_receipt_pdf_is_valid(self):
        from datetime import date
        from decimal import Decimal

        from apps.core.pdf import receipt_pdf

        pdf = receipt_pdf(
            title="Donation Receipt", receipt_number="DON-2026-00001",
            amount=Decimal("5000"), currency="PKR",
            payer_label="Donor", payer_value="Abdul Karim",
            rows=[("Purpose", "Ramzan drive")], issued_on=date(2026, 6, 7),
            received_by="Imran Chairman",
        )
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 1000)

    def test_id_card_pdf_is_valid(self):
        from datetime import date

        from apps.core.pdf import id_card_pdf

        pdf = id_card_pdf(
            member_name="Fatima Khan", member_number="MWAR-000019",
            membership_class="Permanent Member (مستقل ممبر)", residency="Owner (مالک)",
            issued_on=date(2026, 6, 6), expires_on=None,
            verify_url="http://example/members/verify/abc/", status="Active",
        )
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 1000)


class ApplicationDocumentAccessTests(TestCase):
    """Reviewers with view_pii can open uploaded identity docs; others cannot,
    and every successful read is audited as a PII_ACCESS event."""

    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        sector = Sector.objects.create(name="Sector D", code="D")
        sub = SubSector.objects.create(sector=sector, name="Sub 1", code="1")
        prop = Property.objects.create(sub_sector=sub, house_number="9")
        self.app = MembershipApplication.objects.create(
            full_name="Sara Ali", father_or_husband_name="Ali", cnic=CNIC,
            phone="0301-1112233", property=prop, residency_type=ResidencyType.OWNER,
            declaration_accepted=True,
        )
        self.doc = self.app.documents.create(
            doc_type="cnic_front",
            file=SimpleUploadedFile("cnic_front.txt", b"id-bytes", content_type="text/plain"),
        )
        self.url = f"/members/staff/documents/{self.doc.pk}/"

        # A reviewer needs both staff-group membership (to pass @staff_member_test)
        # and the view_pii permission (to pass the document gate).
        staff_group = Group.objects.create(name="Secretary")
        self.reviewer = User.objects.create_user("rev@x.pk", "pw1234567890", full_name="Rev")
        self.reviewer.groups.add(staff_group)
        self.reviewer.user_permissions.add(Permission.objects.get(codename="view_pii"))
        # A staff member without view_pii.
        self.plain_staff = User.objects.create_user("fin@x.pk", "pw1234567890", full_name="Fin")
        self.plain_staff.groups.add(staff_group)

    def test_reviewer_with_view_pii_gets_file_and_audit(self):
        self.client.force_login(self.reviewer)
        before = AuditLog.objects.filter(
            action="pii_access", entity_type="ApplicationDocument").count()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        body = b"".join(r.streaming_content) if hasattr(r, "streaming_content") else r.content
        self.assertEqual(body, b"id-bytes")
        after = AuditLog.objects.filter(
            action="pii_access", entity_type="ApplicationDocument").count()
        self.assertEqual(after, before + 1)

    def test_staff_without_view_pii_is_forbidden(self):
        self.client.force_login(self.plain_staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)


class ApplicationLifecycleTests(TestCase):
    """Re-apply blocking, applicant notifications, and the status tracker."""

    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        sector = Sector.objects.create(name="Sector W", code="W")
        sub = SubSector.objects.create(sector=sector, name="Sub 1", code="1")
        self.prop = Property.objects.create(sub_sector=sub, house_number="8",
                                            status=Property.Status.OCCUPIED)
        self.applicant = User.objects.create_user("hopeful@x.pk", "pw1234567890",
                                                   full_name="Hopeful One")
        self.secretary = User.objects.create_user("sec@x.pk", "pw1234567890", full_name="Sec")
        self.chairman = User.objects.create_user("chair@x.pk", "pw1234567890", full_name="Chair")
        self.chairman.user_permissions.add(Permission.objects.get(codename="approve_membership"))
        self._doc = SimpleUploadedFile

    def _app(self):
        app = MembershipApplication.objects.create(
            full_name="Hopeful One", father_or_husband_name="F", cnic=CNIC,
            phone="0301-2345678", property=self.prop, residency_type=ResidencyType.OWNER,
            declaration_accepted=True, applicant_user=self.applicant,
        )
        for dt in ("cnic_front", "cnic_back"):
            app.documents.create(doc_type=dt, file=self._doc(f"{dt}.txt", b"x"))
        return app

    def test_cannot_apply_with_open_application(self):
        app = self._app()
        submit_application(app)
        self.assertIsNotNone(open_application_for(self.applicant))
        self.client.force_login(self.applicant)
        r = self.client.get("/members/apply/")
        self.assertRedirects(r, "/members/my-application/")

    def test_active_member_cannot_apply_again(self):
        app = self._app()
        submit_application(app)
        secretary_review(app, self.secretary, decision="approve")
        chairman_approve(app, self.chairman)
        self.applicant.refresh_from_db()
        self.client.force_login(self.applicant)
        r = self.client.get("/members/apply/")
        self.assertRedirects(r, "/members/dashboard/")

    def test_applicant_is_notified_at_each_stage(self):
        from apps.content.models import Notification

        app = self._app()
        submit_application(app)
        secretary_review(app, self.secretary, decision="approve")
        chairman_approve(app, self.chairman)
        titles = set(Notification.objects.filter(recipient=self.applicant)
                     .values_list("title", flat=True))
        self.assertIn("Application submitted", titles)
        self.assertIn("Application passed first review", titles)
        self.assertTrue(any(t.startswith("Membership approved") for t in titles))

    def test_rejection_notifies_with_reason(self):
        from apps.content.models import Notification

        app = self._app()
        submit_application(app)
        secretary_review(app, self.secretary, decision="reject", notes="Incomplete CNIC scan")
        n = Notification.objects.get(recipient=self.applicant, title="Application not approved")
        self.assertIn("Incomplete CNIC scan", n.body)

    def test_status_page_shows_tracker(self):
        app = self._app()
        submit_application(app)
        self.client.force_login(self.applicant)
        r = self.client.get("/members/my-application/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "My Membership Application")
