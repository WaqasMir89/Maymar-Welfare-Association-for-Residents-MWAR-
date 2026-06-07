"""Public/member content: projects, notices, news, events."""

from __future__ import annotations

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.locality.models import Sector


class Project(TimeStampedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        ACTIVE = "active", _("Active")
        COMPLETED = "completed", _("Completed")
        ON_HOLD = "on_hold", _("On hold")

    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    summary = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED)
    budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_public = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:200]
        super().save(*args, **kwargs)


class ProjectUpdate(TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="updates")
    title = models.CharField(max_length=180)
    body = models.TextField()
    published_at = models.DateTimeField(default=timezone.now)
    is_public = models.BooleanField(default=True)

    class Meta:
        ordering = ["-published_at"]

    def __str__(self) -> str:
        return self.title


class Notice(TimeStampedModel):
    class Audience(models.TextChoices):
        PUBLIC = "public", _("Public")
        ALL_MEMBERS = "all_members", _("All members")
        SECTOR = "sector", _("Specific sector")

    title = models.CharField(max_length=180)
    body = models.TextField()
    audience = models.CharField(max_length=12, choices=Audience.choices, default=Audience.ALL_MEMBERS)
    sector = models.ForeignKey(Sector, null=True, blank=True, on_delete=models.SET_NULL)
    published_at = models.DateTimeField(default=timezone.now)
    # Delivery channels chosen for this notice.
    via_in_app = models.BooleanField(default=True)
    via_sms = models.BooleanField(default=False)
    via_email = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-published_at"]
        permissions = [("broadcast_notice", "Can broadcast notices to members")]

    def __str__(self) -> str:
        return self.title


class Event(TimeStampedModel):
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    is_public = models.BooleanField(default=True)
    rsvp_enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ["starts_at"]

    def __str__(self) -> str:
        return self.title


class PublicDocument(TimeStampedModel):
    """A downloadable PDF in the public document library — bylaws, forms,
    audited accounts, meeting minutes. Uploaded by staff who hold
    ``content.manage_documents``; served to anyone when ``is_published``."""

    class Category(models.TextChoices):
        BYLAWS = "bylaws", _("Constitution & bylaws")
        FORMS = "forms", _("Forms")
        REPORTS = "reports", _("Financial reports")
        MINUTES = "minutes", _("Meeting minutes")
        OTHER = "other", _("Other")

    title = models.CharField(max_length=200)
    description = models.CharField(max_length=400, blank=True)
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.OTHER)
    file = models.FileField(
        upload_to="public_documents/%Y/%m/",
        validators=[FileExtensionValidator(allowed_extensions=["pdf"])],
    )
    is_published = models.BooleanField(default=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="uploaded_documents",
    )

    class Meta:
        ordering = ["category", "-created_at"]
        permissions = [("manage_documents", "Can upload and manage public documents")]

    def __str__(self) -> str:
        return self.title


class OrganizationProfile(TimeStampedModel):
    """Singleton holding the public 'About' content — the Chairman's message,
    photo, vision, mission and roadmap year. Edited by staff in the admin."""

    chairman_name = models.CharField(max_length=120, blank=True)
    chairman_title = models.CharField(max_length=80, default="Chairman")
    chairman_photo = models.ImageField(upload_to="organization/", null=True, blank=True)
    chairman_message = models.TextField(blank=True)
    vision = models.TextField(blank=True)
    mission = models.TextField(blank=True)
    roadmap_year = models.PositiveIntegerField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        permissions = [("manage_organization", "Can edit the organization About page")]

    def __str__(self) -> str:
        return "Organization profile"

    def save(self, *args, **kwargs):
        self.pk = 1                      # enforce a single row
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "OrganizationProfile":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class OrganizationGoal(TimeStampedModel):
    """A strategic goal shown on the About page."""

    profile = models.ForeignKey(
        OrganizationProfile, on_delete=models.CASCADE, related_name="goals"
    )
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.title


class RoadmapMilestone(TimeStampedModel):
    """One item on the annual roadmap timeline."""

    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        IN_PROGRESS = "in_progress", _("In progress")
        DONE = "done", _("Done")

    profile = models.ForeignKey(
        OrganizationProfile, on_delete=models.CASCADE, related_name="milestones"
    )
    order = models.PositiveIntegerField(default=0)
    period = models.CharField(max_length=40, help_text="e.g. Q1 · Jan–Mar")
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=400, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PLANNED)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.period}: {self.title}"


class OrganizationAsset(TimeStampedModel):
    """A physical or financial asset owned by the association. Uploaded by
    senior staff (``content.manage_assets``) and listed publicly for openness."""

    class Category(models.TextChoices):
        LAND = "land", _("Land & plots")
        BUILDING = "building", _("Buildings")
        VEHICLE = "vehicle", _("Vehicles")
        EQUIPMENT = "equipment", _("Equipment")
        FURNITURE = "furniture", _("Furniture & fixtures")
        FUND = "fund", _("Funds & reserves")
        OTHER = "other", _("Other")

    name = models.CharField(max_length=180)
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.OTHER)
    description = models.CharField(max_length=400, blank=True)
    location = models.CharField(max_length=200, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    estimated_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    acquired_on = models.DateField(null=True, blank=True)
    photo = models.ImageField(upload_to="assets/", null=True, blank=True)
    is_public = models.BooleanField(default=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["category", "name"]
        permissions = [("manage_assets", "Can add and manage organization assets")]

    def __str__(self) -> str:
        return self.name


class Notification(TimeStampedModel):
    """A per-user in-app notification (the inbox behind the nav bell)."""

    class Level(models.TextChoices):
        INFO = "info", _("Info")
        SUCCESS = "success", _("Success")
        WARNING = "warning", _("Warning")

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    title = models.CharField(max_length=180)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=300, blank=True)
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    notice = models.ForeignKey(
        Notice, null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications"
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read"])]

    def __str__(self) -> str:
        return f"{self.title} → {self.recipient}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at", "updated_at"])
