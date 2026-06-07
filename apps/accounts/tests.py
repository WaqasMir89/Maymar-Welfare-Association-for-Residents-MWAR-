"""Authentication flows, including the password-reset journey."""

from __future__ import annotations

import re

from django.core import mail
from django.test import TestCase, override_settings

from apps.accounts.models import User


class LoginPageTests(TestCase):
    def test_login_page_offers_password_reset(self):
        r = self.client.get("/accounts/login/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "/accounts/password-reset/")
        self.assertContains(r, "Forgot password")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("resident@mwar.org.pk", "OldPass#123",
                                              full_name="Resident One")

    def test_full_reset_journey_changes_password(self):
        # 1) Request a reset link.
        r = self.client.post("/accounts/password-reset/", {"email": self.user.email})
        self.assertRedirects(r, "/accounts/password-reset/done/")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("M.W.A.R", mail.outbox[0].subject)

        # 2) The email carries a working confirm link.
        link = re.search(r"/accounts/reset/[^\s]+", mail.outbox[0].body).group(0)
        set_url = self.client.get(link)["Location"]   # redirects to the set-password URL

        # 3) Submit a new password.
        r = self.client.post(set_url, {"new_password1": "BrandNew#2026",
                                       "new_password2": "BrandNew#2026"})
        self.assertRedirects(r, "/accounts/reset/done/")

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNew#2026"))

    def test_unknown_email_does_not_leak_or_send(self):
        # Always lands on the same "done" page — no account enumeration.
        r = self.client.post("/accounts/password-reset/", {"email": "ghost@nowhere.pk"})
        self.assertRedirects(r, "/accounts/password-reset/done/")
        self.assertEqual(len(mail.outbox), 0)


class StaffNavLinkTests(TestCase):
    """Every committee role — including Finance Officer — must see the Staff
    dashboard link and be able to open it. Regression for the old check that
    only showed it to holders of members.review_application."""

    def _user_in(self, group_name):
        from django.contrib.auth.models import Group

        u = User.objects.create_user(f"{group_name}@x.pk", "pw1234567890")
        u.groups.add(Group.objects.create(name=group_name))
        return u

    def test_finance_officer_sees_staff_link_and_dashboard(self):
        finance = self._user_in("Finance Officer")
        self.client.force_login(finance)
        home = self.client.get("/")
        self.assertContains(home, "/staff/")
        self.assertEqual(self.client.get("/staff/").status_code, 200)

    def test_plain_member_does_not_see_staff_link(self):
        member = User.objects.create_user("plain@x.pk", "pw1234567890")
        self.client.force_login(member)
        home = self.client.get("/").content.decode()
        self.assertNotIn(">Staff<", home)
        self.assertEqual(self.client.get("/staff/").status_code, 302)
