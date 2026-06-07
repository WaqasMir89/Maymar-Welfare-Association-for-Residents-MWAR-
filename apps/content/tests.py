"""Notifications fan-out + inbox, and events visibility."""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.content.models import Event, Notice, Notification
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
