"""Notifications fan-out + inbox, and events visibility."""

from __future__ import annotations

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.content.models import (
    Event,
    Notice,
    Notification,
    OrganizationProfile,
    PublicDocument,
)
from apps.content.services import fan_out_notice, notify
from apps.locality.models import Property, Sector, SubSector
from apps.members.models import MemberProfile, Residency, ResidencyType


class NotificationFanOutTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("s@x.pk", "password123", is_staff=True)
        # A member with a login account.
        self.member_user = User.objects.create_user("m@x.pk", "password123")
        self.profile = MemberProfile.objects.create(
            full_name="Member One", father_or_husband_name="X", cnic="42101-1111111-1",
            phone="0300-1111111", status=MemberProfile.Status.ACTIVE, user=self.member_user,
        )

    def test_fan_out_reaches_members_and_staff(self):
        notice = Notice.objects.create(title="Hello", body="Body",
                                       audience=Notice.Audience.ALL_MEMBERS)
        created = fan_out_notice(notice)
        self.assertEqual(created, 2)                       # member + staff
        self.assertEqual(Notification.objects.filter(notice=notice).count(), 2)

    def test_via_in_app_false_creates_nothing(self):
        notice = Notice.objects.create(title="Silent", via_in_app=False)
        self.assertEqual(fan_out_notice(notice), 0)

    def test_mark_read_sets_timestamp(self):
        n = notify(self.member_user, title="Hi")
        self.assertFalse(n.is_read)
        n.mark_read()
        n.refresh_from_db()
        self.assertTrue(n.is_read)
        self.assertIsNotNone(n.read_at)

    def test_notice_create_view_fans_out(self):
        self.staff.user_permissions.add(
            __import__("django.contrib.auth.models", fromlist=["Permission"]).Permission.objects.get(
                codename="broadcast_notice", content_type__app_label="content")
        )
        self.client.force_login(self.staff)
        r = self.client.post("/content/notices/new/",
                             {"title": "Boil water", "body": "Advisory",
                              "audience": Notice.Audience.PUBLIC})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Notification.objects.filter(title="Boil water").exists())


class NotificationScopingTests(TestCase):
    def test_inbox_only_shows_own(self):
        a = User.objects.create_user("a@x.pk", "password123")
        b = User.objects.create_user("b@x.pk", "password123")
        notify(a, title="For A")
        notify(b, title="For B")
        self.client.force_login(a)
        r = self.client.get("/content/notifications/")
        self.assertContains(r, "For A")
        self.assertNotContains(r, "For B")


class EventVisibilityTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.pub = Event.objects.create(title="Public Drive", starts_at=now, is_public=True)
        self.priv = Event.objects.create(title="Members AGM", starts_at=now, is_public=False)

    def test_anonymous_sees_only_public(self):
        r = self.client.get("/content/events/")
        self.assertContains(r, "Public Drive")
        self.assertNotContains(r, "Members AGM")

    def test_authenticated_sees_all(self):
        self.client.force_login(User.objects.create_user("u@x.pk", "password123"))
        r = self.client.get("/content/events/")
        self.assertContains(r, "Members AGM")


class PublicDocumentTests(TestCase):
    """Staff with manage_documents upload PDFs; anyone downloads published ones."""

    PDF = b"%PDF-1.4 minimal"

    def setUp(self):
        self.manager = User.objects.create_user("mgr@x.pk", "password123")
        self.manager.user_permissions.add(
            Permission.objects.get(codename="manage_documents",
                                    content_type__app_label="content")
        )
        self.plain = User.objects.create_user("plain@x.pk", "password123")

    def _upload(self, client, name="bylaws.pdf", ctype="application/pdf", **extra):
        data = {"title": "Constitution", "category": "bylaws", "is_published": "on"}
        data.update(extra)
        data["file"] = SimpleUploadedFile(name, self.PDF, content_type=ctype)
        return client.post("/content/documents/upload/", data)

    def test_manager_can_upload_pdf(self):
        self.client.force_login(self.manager)
        r = self._upload(self.client)
        self.assertEqual(r.status_code, 302)
        doc = PublicDocument.objects.get(title="Constitution")
        self.assertEqual(doc.category, "bylaws")
        self.assertEqual(doc.uploaded_by, self.manager)
        doc.file.delete(save=False)

    def test_non_pdf_is_rejected(self):
        self.client.force_login(self.manager)
        self._upload(self.client, name="x.exe", ctype="application/octet-stream")
        self.assertEqual(PublicDocument.objects.count(), 0)

    def test_user_without_permission_cannot_upload(self):
        self.client.force_login(self.plain)
        # Friendly redirect to the library (not a bare 403), and nothing saved.
        r = self.client.get("/content/documents/upload/")
        self.assertRedirects(r, "/content/documents/")
        self.assertEqual(self._upload(self.client).status_code, 302)
        self.assertEqual(PublicDocument.objects.count(), 0)

    def test_anonymous_upload_redirects_to_login(self):
        r = self.client.get("/content/documents/upload/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/accounts/login", r["Location"])

    def test_public_can_download_published_but_not_draft(self):
        doc = PublicDocument.objects.create(
            title="Published", category="forms", is_published=True,
            file=SimpleUploadedFile("p.pdf", self.PDF, content_type="application/pdf"),
        )
        draft = PublicDocument.objects.create(
            title="Draft", category="minutes", is_published=False,
            file=SimpleUploadedFile("d.pdf", self.PDF, content_type="application/pdf"),
        )
        r = self.client.get(f"/content/documents/{doc.pk}/download/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        body = b"".join(r.streaming_content) if hasattr(r, "streaming_content") else r.content
        self.assertEqual(body, self.PDF)
        self.assertEqual(self.client.get(f"/content/documents/{draft.pk}/download/").status_code, 404)
        doc.file.delete(save=False)
        draft.file.delete(save=False)

    def test_list_page_renders_for_public(self):
        self.assertEqual(self.client.get("/content/documents/").status_code, 200)


class OrganizationProfileTests(TestCase):
    def test_profile_is_a_singleton(self):
        a = OrganizationProfile.load()
        a.chairman_name = "Imran"
        a.save()
        b = OrganizationProfile.load()
        self.assertEqual(a.pk, 1)
        self.assertEqual(b.pk, 1)
        self.assertEqual(OrganizationProfile.objects.count(), 1)
        self.assertEqual(b.chairman_name, "Imran")

    def test_about_page_shows_chairman_message_and_roadmap(self):
        org = OrganizationProfile.load()
        org.chairman_name = "Imran Chairman"
        org.chairman_message = "Welcome to the M.W.A.R family."
        org.vision = "A safe neighbourhood."
        org.save()
        org.goals.create(order=0, title="Transparent finances")
        org.milestones.create(order=0, period="Q1", title="Digitise dues", status="done")

        r = self.client.get("/about/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Message from the Chairman")
        self.assertContains(r, "Welcome to the M.W.A.R family.")
        self.assertContains(r, "Transparent finances")
        self.assertContains(r, "Digitise dues")

    def test_about_page_renders_without_content(self):
        # A fresh install with an empty profile must still render.
        self.assertEqual(self.client.get("/about/").status_code, 200)


class OrganizationAssetTests(TestCase):
    def setUp(self):
        from apps.content.models import OrganizationAsset

        self.senior = User.objects.create_user("senior@x.pk", "password123")
        self.senior.user_permissions.add(
            Permission.objects.get(codename="manage_assets", content_type__app_label="content")
        )
        OrganizationAsset.objects.create(name="Community Hall", category="building",
                                         estimated_value=1000000, is_public=True)
        OrganizationAsset.objects.create(name="Secret Plot", category="land", is_public=False)

    def test_public_sees_only_public_assets(self):
        r = self.client.get("/content/assets/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Community Hall")
        self.assertNotContains(r, "Secret Plot")

    def test_manager_sees_all_and_can_add(self):
        self.client.force_login(self.senior)
        r = self.client.get("/content/assets/")
        self.assertContains(r, "Secret Plot")
        self.assertEqual(self.client.get("/content/assets/add/").status_code, 200)
        r = self.client.post("/content/assets/add/", {
            "name": "Generator", "category": "equipment", "quantity": "1",
            "estimated_value": "50000", "is_public": "on",
        })
        self.assertRedirects(r, "/content/assets/")
        from apps.content.models import OrganizationAsset

        self.assertTrue(OrganizationAsset.objects.filter(name="Generator").exists())

    def test_non_manager_cannot_add(self):
        plain = User.objects.create_user("plain2@x.pk", "password123")
        self.client.force_login(plain)
        self.assertEqual(self.client.get("/content/assets/add/").status_code, 403)
