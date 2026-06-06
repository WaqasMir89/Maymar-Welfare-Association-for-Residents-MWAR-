"""RWA complaints/ticketing: water, security, sanitation, streetlights, etc."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.locality.models import Property


class Ticket(TimeStampedModel):
    class Category(models.TextChoices):
        WATER = "water", _("Water")
        SEWERAGE = "sewerage", _("Sewerage")
        ELECTRICITY = "electricity", _("Electricity")
        SECURITY = "security", _("Security")
        SANITATION = "sanitation", _("Sanitation")
        STREETLIGHTS = "streetlights", _("Streetlights")
        ENCROACHMENT = "encroachment", _("Encroachment")
        COMMON_AREAS = "common_areas", _("Parks / common areas")
        OTHER = "other", _("Other")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        MEDIUM = "medium", _("Medium")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        ASSIGNED = "assigned", _("Assigned")
        IN_PROGRESS = "in_progress", _("In progress")
        RESOLVED = "resolved", _("Resolved")
        CLOSED = "closed", _("Closed")
        REOPENED = "reopened", _("Reopened")

    ticket_number = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=160)
    description = models.TextField()
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.OTHER)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_tickets",
    )
    property = models.ForeignKey(
        Property, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["ticket_number"])]

    def __str__(self) -> str:
        return f"{self.ticket_number} — {self.title}"

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            year = timezone.now().year
            seq = Ticket.objects.filter(created_at__year=year).count() + 1
            self.ticket_number = f"TKT-{year}-{seq:05d}"
        super().save(*args, **kwargs)


class TicketMessage(TimeStampedModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    body = models.TextField()
    is_internal = models.BooleanField(default=False, help_text="Staff-only note (hidden from member).")

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Message on {self.ticket.ticket_number}"


class TicketAttachment(TimeStampedModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="ticket_files/%Y/%m/")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
