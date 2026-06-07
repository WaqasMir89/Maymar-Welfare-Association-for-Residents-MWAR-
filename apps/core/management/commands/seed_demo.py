"""Seed synthetic demo data for the M.W.A.R platform.

Creates roles, staff users, the Gulshan-e-Maymar locality registry, members
(via the real application→approval workflow), a dues plan with invoices and
some payments, donations, expenses, projects, notices and complaints.

All CNICs are synthetic. Run after migrate:

    python manage.py seed_demo
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.accounts.permissions import CHAIRMAN, FINANCE, MEMBER, SECRETARY
from apps.content.models import Event, Notice, Project, ProjectUpdate
from apps.content.services import fan_out_notice
from apps.dues.models import Donation, DuesInvoice, DuesPlan, Expense
from apps.dues.services import generate_invoices, record_dues_payment
from apps.locality.models import Property, Sector, SubSector
from apps.members.models import MemberProfile, MembershipApplication, ResidencyType
from apps.members.services import chairman_approve, secretary_review, submit_application
from apps.tickets.models import Ticket

FIRST = ["Ahmed", "Fatima", "Bilal", "Ayesha", "Usman", "Sana", "Imran", "Hira",
         "Tariq", "Zainab", "Kamran", "Nida", "Farhan", "Maryam", "Saad", "Rabia"]
LAST = ["Khan", "Malik", "Sheikh", "Qureshi", "Siddiqui", "Ansari", "Baig", "Raza"]
PROFESSIONS = ["Teacher", "Engineer", "Shopkeeper", "Doctor", "Accountant", "Driver", "Tailor"]


def cnic() -> str:
    return f"42101-{random.randint(1000000, 9999999)}-{random.randint(1, 9)}"


def phone() -> str:
    return f"03{random.randint(0,4)}{random.randint(0,9)}-{random.randint(1000000, 9999999)}"


class Command(BaseCommand):
    help = "Populate the database with synthetic demo data."

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(42)
        self.stdout.write("Setting up RBAC roles…")
        call_command("setup_rbac")

        # ---- Superuser ----
        if not User.objects.filter(email="admin@mwar.org.pk").exists():
            User.objects.create_superuser(
                "admin@mwar.org.pk", "admin12345", full_name="System Administrator"
            )
            self.stdout.write(self.style.SUCCESS("  superuser: admin@mwar.org.pk / admin12345"))

        # ---- Staff with roles ----
        staff = {
            ("chairman@mwar.org.pk", "Imran Chairman", CHAIRMAN, StaffProfile.Title.CHAIRMAN),
            ("secretary@mwar.org.pk", "Sana Secretary", SECRETARY, StaffProfile.Title.SECRETARY),
            ("finance@mwar.org.pk", "Bilal Treasurer", FINANCE, StaffProfile.Title.TREASURER),
        }
        users = {}
        for email, name, role, title in staff:
            user, created = User.objects.get_or_create(
                email=email, defaults={"full_name": name, "is_staff": True, "phone": phone()}
            )
            if created:
                user.set_password("staff12345")
                user.save()
            user.groups.add(Group.objects.get(name=role))
            StaffProfile.objects.get_or_create(user=user, defaults={"title": title})
            users[role] = user
        self.stdout.write(self.style.SUCCESS("  staff: chairman/secretary/finance @mwar.org.pk / staff12345"))

        secretary = users[SECRETARY]
        chairman = users[CHAIRMAN]
        finance = users[FINANCE]

        # ---- Locality registry ----
        self.stdout.write("Building locality registry…")
        properties: list[Property] = []
        for sec_code in ["V", "W", "X"]:
            sector, _ = Sector.objects.get_or_create(
                code=sec_code, defaults={"name": f"Sector {sec_code}"}
            )
            for sub_n in [1, 2]:
                sub, _ = SubSector.objects.get_or_create(
                    sector=sector, code=str(sub_n), defaults={"name": f"Sub-Sector {sub_n}"}
                )
                for house in range(1, 9):
                    prop, _ = Property.objects.get_or_create(
                        sub_sector=sub, house_number=f"{house}",
                        defaults={"status": Property.Status.OCCUPIED},
                    )
                    properties.append(prop)
        self.stdout.write(self.style.SUCCESS(f"  {len(properties)} properties across 3 sectors"))

        # ---- Members via the real application → approval workflow ----
        self.stdout.write("Registering members through the application workflow…")
        approved = 0
        for i, prop in enumerate(properties[:24]):
            rt = ResidencyType.OWNER if i % 3 else ResidencyType.TENANT
            app = MembershipApplication.objects.create(
                full_name=f"{random.choice(FIRST)} {random.choice(LAST)}",
                father_or_husband_name=f"{random.choice(FIRST)} {random.choice(LAST)}",
                cnic=cnic(),
                phone=phone(),
                profession=random.choice(PROFESSIONS),
                household_size=random.randint(2, 8),
                property=prop,
                residency_type=rt,
                declaration_accepted=True,
            )
            submit_application(app)
            # Most go all the way through; leave a few in the queue.
            if i % 5 != 0:
                secretary_review(app, secretary, decision="approve", notes="Documents OK.")
                chairman_approve(app, chairman, fee_method="cash")
                approved += 1
            elif i % 5 == 0 and i % 2 == 0:
                secretary_review(app, secretary, decision="approve", notes="Pending Chairman.")
        self.stdout.write(self.style.SUCCESS(f"  {approved} members approved, others left in queue"))

        # ---- Dues plan + billing run + payments ----
        self.stdout.write("Generating dues…")
        plan, _ = DuesPlan.objects.get_or_create(
            name="Monthly Maintenance",
            defaults={"amount": Decimal("1500.00"), "period": DuesPlan.Period.MONTHLY},
        )
        today = timezone.now()
        for back in (1, 0):
            month = (today.month - back - 1) % 12 + 1
            year = today.year if today.month - back >= 1 else today.year - 1
            generate_invoices(plan, year, month)
        # Pay ~70% of invoices.
        for inv in DuesInvoice.objects.all():
            if random.random() < 0.7:
                record_dues_payment(inv, amount=inv.amount_due, method="cash", user=finance)
        self.stdout.write(self.style.SUCCESS(f"  {DuesInvoice.objects.count()} invoices generated"))

        # ---- Donations & expenses ----
        for _ in range(6):
            Donation.objects.create(
                donor_name=f"{random.choice(FIRST)} {random.choice(LAST)}",
                amount=Decimal(random.choice([5000, 10000, 25000, 2000])),
                purpose=random.choice(["Ramzan drive", "Streetlight fund", "Park renovation"]),
                receipt_number=f"DON-{random.randint(10000,99999)}",
                received_by=finance, is_public=True,
            )
        for cat, amt in [("Security guards", 60000), ("Sanitation", 35000),
                         ("Street lighting", 18000), ("Water tanker", 12000)]:
            Expense.objects.create(category=cat, amount=Decimal(amt),
                                   status=Expense.Status.PAID, requested_by=finance,
                                   approved_by=chairman, incurred_on=date.today() - timedelta(days=5))
        # A couple left pending so the approval workflow is demonstrable.
        for cat, amt in [("Generator fuel", 22000), ("CCTV maintenance", 15000)]:
            Expense.objects.create(category=cat, amount=Decimal(amt),
                                   status=Expense.Status.PENDING, requested_by=finance,
                                   incurred_on=date.today() - timedelta(days=2))

        # ---- Projects, notices, tickets ----
        for title, status, budget in [
            ("Main Park Renovation", Project.Status.ACTIVE, 850000),
            ("Streetlight Upgrade — Sector W", Project.Status.COMPLETED, 320000),
            ("Community Water Filtration Plant", Project.Status.PLANNED, 1200000),
        ]:
            p, created = Project.objects.get_or_create(
                title=title, defaults={"status": status, "budget": Decimal(budget),
                                       "summary": f"{title} for the residents of Gulshan-e-Maymar."})
            if created:
                ProjectUpdate.objects.create(project=p, title="Project kicked off",
                                             body="Work has begun; updates will follow here.")

        # ---- A demo member login (seed members otherwise have no account) ----
        first_profile = MemberProfile.objects.filter(status="active").order_by("member_number").first()
        if first_profile and not first_profile.user:
            member_user, created = User.objects.get_or_create(
                email="member@mwar.org.pk",
                defaults={"full_name": first_profile.full_name, "phone": first_profile.phone},
            )
            if created:
                member_user.set_password("member12345")
                member_user.save()
                member_user.groups.add(Group.objects.get(name=MEMBER))
            first_profile.user = member_user
            first_profile.save(update_fields=["user"])

        # ---- Notices (fan out to in-app notifications) ----
        n1, c1 = Notice.objects.get_or_create(title="Water supply schedule revised",
            defaults={"body": "From Monday, water will be supplied 6–9am and 6–9pm.",
                      "audience": Notice.Audience.PUBLIC, "created_by": secretary})
        n2, c2 = Notice.objects.get_or_create(title="Annual General Meeting — Sunday 10am",
            defaults={"body": "All members are invited to the AGM at the community hall.",
                      "audience": Notice.Audience.ALL_MEMBERS, "created_by": chairman})
        for notice, created in ((n1, c1), (n2, c2)):
            if created:
                fan_out_notice(notice)

        # ---- Community events ----
        Event.objects.get_or_create(title="Annual General Meeting", defaults={
            "description": "Yearly review of accounts, projects and elections.",
            "starts_at": timezone.now() + timedelta(days=14, hours=10),
            "location": "Community Hall, Sector W", "is_public": False})
        Event.objects.get_or_create(title="Neighbourhood Cleanliness Drive", defaults={
            "description": "Join hands to clean and green our streets. Tools provided.",
            "starts_at": timezone.now() + timedelta(days=5, hours=8),
            "location": "Sector W Park", "is_public": True})
        Event.objects.get_or_create(title="Eid Milan Community Gathering", defaults={
            "description": "Past event — a wonderful evening of community bonding.",
            "starts_at": timezone.now() - timedelta(days=20),
            "location": "Community Hall", "is_public": True})

        members_qs = list(User.objects.filter(member_profile__isnull=False)[:5])
        ticket_data = [
            ("Streetlight not working", Ticket.Category.STREETLIGHTS, Ticket.Priority.MEDIUM),
            ("Water pressure very low", Ticket.Category.WATER, Ticket.Priority.HIGH),
            ("Garbage not collected for 3 days", Ticket.Category.SANITATION, Ticket.Priority.HIGH),
            ("Security guard absent at night", Ticket.Category.SECURITY, Ticket.Priority.URGENT),
        ]
        for i, (title, cat, pri) in enumerate(ticket_data):
            Ticket.objects.get_or_create(title=title, defaults={
                "description": f"Reported issue: {title}.", "category": cat, "priority": pri,
                "created_by": members_qs[i % len(members_qs)] if members_qs else None,
                "status": Ticket.Status.OPEN if i % 2 else Ticket.Status.IN_PROGRESS})

        self.stdout.write(self.style.SUCCESS("\nDemo data ready. Log in as admin@mwar.org.pk / admin12345"))
