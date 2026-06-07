"""Membership service layer.

Keeps the two-step approval, member-number assignment, fee receipt and card
issuance in one transactional place so views stay thin and the rules live
together.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.services import record_audit

from .models import (
    ApplicationDocument,
    FeePayment,
    MemberCard,
    MemberProfile,
    Membership,
    MembershipApplication,
    Residency,
    class_for_residency,
)


class ApprovalError(Exception):
    """Raised when an approval precondition is not met."""


# Statuses that mean "this application is still in progress / not yet decided".
OPEN_APPLICATION_STATUSES = [
    MembershipApplication.Status.DRAFT,
    MembershipApplication.Status.SUBMITTED,
    MembershipApplication.Status.DOCS_REQUIRED,
    MembershipApplication.Status.UNDER_REVIEW,
    MembershipApplication.Status.SECRETARY_APPROVED,
]


def open_application_for(user) -> MembershipApplication | None:
    """The user's not-yet-decided application, if any (blocks re-applying)."""
    if not getattr(user, "is_authenticated", False):
        return None
    return (
        MembershipApplication.objects
        .filter(applicant_user=user, status__in=OPEN_APPLICATION_STATUSES)
        .order_by("-created_at")
        .first()
    )


def _notify_applicant(application, *, title, body, level="info", url="/members/my-application/"):
    """In-app notification to the applicant (no-op for staff walk-ins)."""
    user = application.applicant_user
    if user:
        from apps.content.services import notify

        notify(user, title=title, body=body, url=url, level=level)


def _next_member_number() -> str:
    """Allocate the next ``MWAR-000123`` sequence atomically."""
    prefix = settings.MEMBER_NUMBER_PREFIX
    last = (
        MemberProfile.objects.filter(member_number__startswith=f"{prefix}-")
        .aggregate(m=Max("member_number"))
        .get("m")
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}-{seq:06d}"


def _next_receipt_number() -> str:
    year = timezone.now().year
    prefix = f"FEE-{year}-"
    last = (
        FeePayment.objects.filter(receipt_number__startswith=prefix)
        .aggregate(m=Max("receipt_number"))
        .get("m")
    )
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:05d}"


def submit_application(application: MembershipApplication) -> MembershipApplication:
    """Move a draft to submitted (or docs_required if attachments are missing)."""
    application.declaration_accepted_at = timezone.now()
    if application.has_required_documents():
        application.status = MembershipApplication.Status.SUBMITTED
    else:
        application.status = MembershipApplication.Status.DOCS_REQUIRED
    application.save()
    record_audit(AuditLog.Action.UPDATE, "MembershipApplication", application.pk,
                 metadata={"to": application.status})
    if application.status == MembershipApplication.Status.SUBMITTED:
        _notify_applicant(
            application, level="info",
            title="Application submitted",
            body="We've received your membership application. The Secretary will review it shortly.",
        )
    else:
        _notify_applicant(
            application, level="warning",
            title="More documents needed",
            body="Please upload the required documents so we can process your application.",
        )
    return application


def secretary_review(application: MembershipApplication, user, *, decision: str, notes: str = ""):
    """First-stage review by the Secretary: approve / reject / request docs."""
    application.review_notes = notes
    application.reviewed_by = user
    application.reviewed_at = timezone.now()

    if decision == "approve":
        application.status = MembershipApplication.Status.SECRETARY_APPROVED
        action = AuditLog.Action.APPROVE
        notice = ("Application passed first review",
                  "Good news — the Secretary has approved your application. "
                  "It now awaits the Chairman's final approval.", "success")
    elif decision == "reject":
        application.status = MembershipApplication.Status.REJECTED
        action = AuditLog.Action.REJECT
        notice = ("Application not approved",
                  notes or "Unfortunately your application was not approved. "
                  "Please contact the office for details.", "warning")
    else:  # docs_required
        application.status = MembershipApplication.Status.DOCS_REQUIRED
        action = AuditLog.Action.UPDATE
        notice = ("More documents required",
                  notes or "Please upload the additional documents requested so the "
                  "review can continue.", "warning")

    application.save()
    record_audit(action, "MembershipApplication", application.pk,
                 actor=user, metadata={"stage": "secretary", "decision": decision})
    _notify_applicant(application, title=notice[0], body=notice[1], level=notice[2])
    return application


@transaction.atomic
def chairman_approve(application: MembershipApplication, chairman, *, fee_method: str = "cash"):
    """Final approval. Atomically issues profile + residency + membership +
    fee receipt + card. Idempotent: a re-run on an approved application is a
    no-op that returns the existing profile."""
    if application.status == MembershipApplication.Status.APPROVED and application.member_profile_id:
        return application.member_profile

    if application.status != MembershipApplication.Status.SECRETARY_APPROVED:
        raise ApprovalError("Application must be Secretary-approved before final approval.")

    secretary = application.reviewed_by

    profile = MemberProfile.objects.create(
        user=application.applicant_user,
        member_number=_next_member_number(),
        full_name=application.full_name,
        father_or_husband_name=application.father_or_husband_name,
        cnic=application.cnic,
        phone=application.phone,
        profession=application.profession,
        household_size=application.household_size,
        status=MemberProfile.Status.ACTIVE,
        join_date=timezone.now().date(),
    )

    if application.property_id:
        Residency.objects.create(
            member=profile,
            property=application.property,
            residency_type=application.residency_type,
            is_current=True,
        )

    Membership.objects.create(
        member=profile,
        membership_class=class_for_residency(application.residency_type),
        approved_by_secretary=secretary,
        approved_by_chairman=chairman,
        approved_at=timezone.now(),
    )

    fee = FeePayment.objects.create(
        member=profile,
        application=application,
        amount=Decimal(settings.REGISTRATION_FEE),
        method=fee_method,
        receipt_number=_next_receipt_number(),
        received_by=chairman,
    )

    card = MemberCard.objects.create(member=profile, member_number=profile.member_number)

    application.status = MembershipApplication.Status.APPROVED
    application.member_profile = profile
    application.reviewed_at = timezone.now()
    application.save(update_fields=["status", "member_profile", "reviewed_at", "updated_at"])

    record_audit(AuditLog.Action.APPROVE, "MembershipApplication", application.pk,
                 actor=chairman, metadata={
                     "stage": "chairman", "member_number": profile.member_number,
                     "receipt": fee.receipt_number, "card_token": str(card.qr_token),
                 })
    record_audit(AuditLog.Action.PAYMENT, "FeePayment", fee.pk, actor=chairman,
                 metadata={"amount": str(fee.amount), "receipt": fee.receipt_number})
    _notify_applicant(
        application, level="success", url="/members/dashboard/",
        title="Membership approved 🎉",
        body=(f"Congratulations! Your membership is approved. Your member number is "
              f"{profile.member_number}. Your digital ID card is ready to view."),
    )
    return profile


def log_pii_access(user, profile: MemberProfile, context: str = "view") -> None:
    """Record a PII_ACCESS event whenever an unmasked CNIC/document is read."""
    record_audit(AuditLog.Action.PII_ACCESS, "MemberProfile", profile.pk,
                 actor=user, metadata={"context": context})
