"""Membership domain — the digitized paper form and everything it spawns.

Flow: a :class:`MembershipApplication` (self-service or assisted) collects the
form fields + documents, runs a two-step approval (Secretary → Chairman), and
on approval atomically creates a :class:`MemberProfile`, :class:`Residency`,
:class:`Membership`, :class:`FeePayment` and :class:`MemberCard`.

CNIC is stored encrypted (``EncryptedCharField``) with a separate blind hash
for uniqueness/lookup, and masked everywhere unless the viewer holds
``members.view_pii``.
"""

from __future__ import annotations

import builtins
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.crypto import mask_cnic
from apps.core.fields import EncryptedCharField
from apps.core.models import SoftDeleteModel, TimeStampedModel
from apps.core.validators import cnic_validator, phone_validator
from apps.locality.models import Property


class ResidencyType(models.TextChoices):
    OWNER = "owner", _("Owner (مالک)")
    TENANT = "tenant", _("Tenant (کرایہ دار)")


class MembershipClass(models.TextChoices):
    PERMANENT = "permanent", _("Permanent Member (مستقل ممبر)")
    ASSOCIATE = "associate", _("Associate Member (ایسوسی ایٹ ممبر)")


def class_for_residency(residency_type: str) -> str:
    """Owner → Permanent, Tenant → Associate (constitution rule)."""
    return (
        MembershipClass.PERMANENT
        if residency_type == ResidencyType.OWNER
        else MembershipClass.ASSOCIATE
    )


class MemberProfile(SoftDeleteModel):
    """One per natural person. May predate a login account."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACTIVE = "active", _("Active")
        SUSPENDED = "suspended", _("Suspended")
        EXPIRED = "expired", _("Expired")
        REJECTED = "rejected", _("Rejected")

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="member_profile",
    )
    member_number = models.CharField(max_length=20, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=150)
    father_or_husband_name = models.CharField(max_length=150)

    # Sensitive PII — encrypted at rest, never indexed in clear.
    cnic = EncryptedCharField(validators=[cnic_validator])
    cnic_hash = models.CharField(max_length=64, unique=True, db_index=True, editable=False)

    phone = models.CharField(max_length=20, validators=[phone_validator])
    alt_phone = models.CharField(max_length=20, blank=True, validators=[phone_validator])
    profession = models.CharField(max_length=120, blank=True)
    household_size = models.PositiveSmallIntegerField(default=1)
    photo = models.ImageField(upload_to="member_photos/", null=True, blank=True)

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    join_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["member_number"]),
            models.Index(fields=["status"]),
        ]
        permissions = [
            ("view_pii", "Can view unmasked CNIC and identity documents"),
            ("review_application", "Can review membership applications (first stage)"),
            ("approve_membership", "Can grant final membership approval"),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.member_number or 'unassigned'})"

    def save(self, *args, **kwargs):
        from apps.core.crypto import blind_hash

        # Maintain the lookup hash from the (plaintext) cnic before encryption.
        if self.cnic:
            self.cnic_hash = blind_hash(self.cnic)
        super().save(*args, **kwargs)

    @property
    def masked_cnic(self) -> str:
        return mask_cnic(self.cnic or "")

    def cnic_for(self, user) -> str:
        """Return the CNIC the given user is allowed to see (masked by default).

        Any unmasked read is the caller's responsibility to audit-log via the
        membership service.
        """
        own = self.user_id and getattr(user, "id", None) == self.user_id
        if own or (user and user.has_perm("members.view_pii")):
            return self.cnic
        return self.masked_cnic

    @property
    def current_residency(self):
        return self.residencies.filter(is_current=True).select_related("property").first()

    @property
    def current_membership(self):
        return self.memberships.order_by("-start_date").first()


class Residency(TimeStampedModel):
    """Links a member to a property and records owner/tenant status over time."""

    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="residencies")
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="residencies")
    residency_type = models.CharField(max_length=8, choices=ResidencyType.choices)
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_current", "-start_date"]
        verbose_name_plural = "residencies"

    def __str__(self) -> str:
        return f"{self.member.full_name} @ {self.property} ({self.get_residency_type_display()})"


class Membership(TimeStampedModel):
    """The association membership granted to a member."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        EXPIRED = "expired", _("Expired")
        SUSPENDED = "suspended", _("Suspended")

    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="memberships")
    membership_class = models.CharField(max_length=10, choices=MembershipClass.choices)
    start_date = models.DateField(default=timezone.now)
    expiry_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    approved_by_secretary = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="secretary_approvals",
    )
    approved_by_chairman = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="chairman_approvals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.member.full_name} — {self.get_membership_class_display()}"


class MembershipApplication(TimeStampedModel):
    """The digital membership form and its review workflow."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SUBMITTED = "submitted", _("Submitted")
        DOCS_REQUIRED = "docs_required", _("Documents required")
        UNDER_REVIEW = "under_review", _("Under review")
        SECRETARY_APPROVED = "secretary_approved", _("Secretary approved")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    applicant_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="applications",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assisted_applications",
        help_text="Staff member, if this was an assisted (walk-in) registration.",
    )

    # Snapshot of the form fields (CNIC encrypted just like the profile).
    full_name = models.CharField(max_length=150)
    father_or_husband_name = models.CharField(max_length=150)
    cnic = EncryptedCharField(validators=[cnic_validator])
    cnic_hash = models.CharField(max_length=64, db_index=True, editable=False, blank=True)
    phone = models.CharField(max_length=20, validators=[phone_validator])
    profession = models.CharField(max_length=120, blank=True)
    household_size = models.PositiveSmallIntegerField(default=1)

    property = models.ForeignKey(
        Property, null=True, blank=True, on_delete=models.SET_NULL, related_name="applications"
    )
    residency_type = models.CharField(max_length=8, choices=ResidencyType.choices)
    requested_class = models.CharField(max_length=10, choices=MembershipClass.choices)

    declaration_accepted = models.BooleanField(default=False)
    declaration_accepted_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    review_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="reviewed_applications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # Set on approval, linking the application to the records it spawned.
    member_profile = models.ForeignKey(
        MemberProfile, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="source_applications",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self) -> str:
        return f"Application #{self.pk} — {self.full_name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        from apps.core.crypto import blind_hash

        if self.cnic:
            self.cnic_hash = blind_hash(self.cnic)
        if self.residency_type and not self.requested_class:
            self.requested_class = class_for_residency(self.residency_type)
        super().save(*args, **kwargs)

    # NOTE: a model field named ``property`` shadows the ``property`` builtin
    # inside this class body, so reference it explicitly via ``builtins``.
    @builtins.property
    def masked_cnic(self) -> str:
        return mask_cnic(self.cnic or "")

    @builtins.property
    def requires_tenancy_agreement(self) -> bool:
        return self.residency_type == ResidencyType.TENANT

    def has_required_documents(self) -> bool:
        types = set(self.documents.values_list("doc_type", flat=True))
        needed = {ApplicationDocument.DocType.CNIC_FRONT}
        if self.requires_tenancy_agreement:
            needed.add(ApplicationDocument.DocType.TENANCY_AGREEMENT)
        return needed.issubset(types)


class ApplicationDocument(TimeStampedModel):
    """An uploaded identity document — stored privately, RBAC-gated."""

    class DocType(models.TextChoices):
        CNIC_FRONT = "cnic_front", _("CNIC (front)")
        CNIC_BACK = "cnic_back", _("CNIC (back)")
        TENANCY_AGREEMENT = "tenancy_agreement", _("Tenancy agreement")
        PHOTO = "photo", _("Photograph")
        OTHER = "other", _("Other")

    application = models.ForeignKey(
        MembershipApplication, on_delete=models.CASCADE, related_name="documents"
    )
    doc_type = models.CharField(max_length=20, choices=DocType.choices)
    # NOTE: private tree, never served by the static handler.
    file = models.FileField(upload_to="application_docs/%Y/%m/")
    verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="verified_documents",
    )

    def __str__(self) -> str:
        return f"{self.get_doc_type_display()} for application #{self.application_id}"


class MemberCard(TimeStampedModel):
    """A printable/QR member ID card; QR resolves to a public verify page."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        REVOKED = "revoked", _("Revoked")

    member = models.OneToOneField(MemberProfile, on_delete=models.CASCADE, related_name="card")
    member_number = models.CharField(max_length=20)
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    def __str__(self) -> str:
        return f"Card {self.member_number}"


class FeePayment(TimeStampedModel):
    """The Rs. 500 registration fee receipt."""

    class Method(models.TextChoices):
        CASH = "cash", _("Cash")
        BANK = "bank_transfer", _("Bank transfer")
        JAZZCASH = "jazzcash", _("JazzCash")
        EASYPAISA = "easypaisa", _("EasyPaisa")

    member = models.ForeignKey(
        MemberProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="fee_payments"
    )
    application = models.ForeignKey(
        MembershipApplication, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="fee_payments",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="PKR")
    method = models.CharField(max_length=16, choices=Method.choices, default=Method.CASH)
    reference = models.CharField(max_length=64, blank=True)
    receipt_number = models.CharField(max_length=24, unique=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="received_fees",
    )
    paid_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"Fee receipt {self.receipt_number} — {self.amount} {self.currency}"
