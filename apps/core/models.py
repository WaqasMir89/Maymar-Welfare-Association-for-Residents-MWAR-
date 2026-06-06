"""Core shared models: timestamped/soft-delete base classes and the audit log."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    """Abstract base giving every row created_at / updated_at."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self) -> "SoftDeleteQuerySet":
        return self.filter(deleted_at__isnull=True)

    def soft_delete(self) -> int:
        return self.update(deleted_at=timezone.now(), is_active=False)


class SoftDeleteModel(TimeStampedModel):
    """Abstract base for people/records that must never be hard-deleted."""

    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        abstract = True

    def soft_delete(self) -> None:
        self.is_active = False
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_active", "deleted_at", "updated_at"])


class AuditLog(models.Model):
    """Append-only audit trail.

    Records every state-changing action and, critically, a dedicated
    ``PII_ACCESS`` event for any read of a CNIC or identity document.
    Rows are never updated or deleted in place (tamper-evident).
    """

    class Action(models.TextChoices):
        CREATE = "create", _("Create")
        UPDATE = "update", _("Update")
        DELETE = "delete", _("Delete")
        APPROVE = "approve", _("Approve")
        REJECT = "reject", _("Reject")
        PAYMENT = "payment", _("Payment")
        LOGIN = "login", _("Login")
        PII_ACCESS = "pii_access", _("PII access")

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)
    entity_type = models.CharField(max_length=64, db_index=True)
    entity_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "audit log entry"
        verbose_name_plural = "audit log"

    def __str__(self) -> str:
        who = self.actor or "system"
        return f"{who} · {self.action} · {self.entity_type}#{self.entity_id}"
