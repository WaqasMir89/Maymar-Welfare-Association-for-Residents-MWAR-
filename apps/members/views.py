"""Membership views: public application, staff queue/review, dashboard, card."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.accounts.permissions import staff_member_test

from .forms import ApplicationForm, DocumentUploadForm, ReviewForm
from .models import (
    ApplicationDocument,
    FeePayment,
    MemberCard,
    MemberProfile,
    MembershipApplication,
)
from .services import ApprovalError, chairman_approve, log_pii_access, secretary_review, submit_application


def _pdf_response(data: bytes, filename: str, *, download: bool = False) -> HttpResponse:
    response = HttpResponse(data, content_type="application/pdf")
    disp = "attachment" if download else "inline"
    response["Content-Disposition"] = f'{disp}; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Public application flow (works for self-service and assisted staff entry)
# ---------------------------------------------------------------------------
def apply_start(request: HttpRequest) -> HttpResponse:
    from apps.accounts.permissions import is_staff_member
    from .services import open_application_for

    acting_as_applicant = request.user.is_authenticated and not is_staff_member(request.user)

    # A member may not start a fresh application while one is still undecided,
    # or once they're already an active member. Staff (assisted walk-ins) are exempt.
    if acting_as_applicant:
        if getattr(request.user, "member_profile", None):
            messages.info(request, _("You're already a registered member."))
            return redirect("members:dashboard")
        existing = open_application_for(request.user)
        if existing:
            messages.info(
                request,
                _("You already have an application in progress. You can track its status here."),
            )
            if existing.status == MembershipApplication.Status.DRAFT:
                return redirect("members:apply_documents", pk=existing.pk)
            return redirect("members:my_application")

    form = ApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        application = form.save(commit=False)
        if request.user.is_authenticated:
            if is_staff_member(request.user):
                application.submitted_by = request.user
            else:
                application.applicant_user = request.user
        application.save()
        messages.success(request, _("Application started. Now upload your documents."))
        return redirect("members:apply_documents", pk=application.pk)
    return render(request, "members/apply_form.html", {"form": form})


def apply_documents(request: HttpRequest, pk: int) -> HttpResponse:
    application = get_object_or_404(MembershipApplication, pk=pk)
    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.application = application
            doc.save()
            messages.success(request, _("Document uploaded."))
            return redirect("members:apply_documents", pk=pk)
    else:
        form = DocumentUploadForm()
    return render(
        request,
        "members/apply_documents.html",
        {"application": application, "form": form, "documents": application.documents.all()},
    )


def apply_submit(request: HttpRequest, pk: int) -> HttpResponse:
    application = get_object_or_404(MembershipApplication, pk=pk)
    if request.method == "POST":
        submit_application(application)
        return redirect("members:apply_success", pk=pk)
    return render(request, "members/apply_review.html", {"application": application})


def apply_success(request: HttpRequest, pk: int) -> HttpResponse:
    application = get_object_or_404(MembershipApplication, pk=pk)
    return render(request, "members/apply_success.html", {"application": application})


# Ordered lifecycle for the applicant-facing status tracker.
APPLICATION_STEPS = [
    (MembershipApplication.Status.SUBMITTED, _("Submitted")),
    (MembershipApplication.Status.UNDER_REVIEW, _("Under review")),
    (MembershipApplication.Status.SECRETARY_APPROVED, _("Secretary approved")),
    (MembershipApplication.Status.APPROVED, _("Approved")),
]


@login_required
def my_application(request: HttpRequest) -> HttpResponse:
    """Let an applicant track the status of their membership application(s)."""
    applications = (
        MembershipApplication.objects
        .filter(applicant_user=request.user)
        .select_related("property", "member_profile")
        .order_by("-created_at")
    )
    latest = applications.first()

    # Build a simple stepper for the latest application.
    steps = []
    if latest and latest.status != MembershipApplication.Status.REJECTED:
        order = [s for s, _ in APPLICATION_STEPS]
        current_index = order.index(latest.status) if latest.status in order else -1
        if latest.status == MembershipApplication.Status.DOCS_REQUIRED:
            current_index = 0
        for i, (value, label) in enumerate(APPLICATION_STEPS):
            steps.append({"label": label, "done": i <= current_index,
                          "current": i == current_index})

    return render(request, "members/my_application.html", {
        "applications": applications, "latest": latest, "steps": steps,
        "Status": MembershipApplication.Status,
    })


# ---------------------------------------------------------------------------
# Staff queue + two-step review
# ---------------------------------------------------------------------------
@staff_member_test
def application_queue(request: HttpRequest) -> HttpResponse:
    qs = MembershipApplication.objects.select_related("property__sub_sector__sector")
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    else:
        qs = qs.exclude(status=MembershipApplication.Status.DRAFT)
    page = Paginator(qs.order_by("-created_at"), 20).get_page(request.GET.get("page"))
    counts = {
        s.value: MembershipApplication.objects.filter(status=s.value).count()
        for s in MembershipApplication.Status
    }
    return render(
        request,
        "members/queue.html",
        {"applications": page, "counts": counts, "status": status,
         "status_choices": MembershipApplication.Status.choices},
    )


@staff_member_test
def application_detail(request: HttpRequest, pk: int) -> HttpResponse:
    application = get_object_or_404(
        MembershipApplication.objects.select_related("property"), pk=pk
    )

    # Showing the unmasked CNIC to a view_pii holder is a PII access event —
    # logged on every read, whether or not a member profile exists yet.
    can_view_pii = request.user.has_perm("members.view_pii")
    shown_cnic = application.cnic if can_view_pii else application.masked_cnic
    if can_view_pii:
        from apps.core.models import AuditLog
        from apps.core.services import record_audit

        record_audit(
            AuditLog.Action.PII_ACCESS,
            "MembershipApplication",
            application.pk,
            actor=request.user,
            metadata={"context": "application_review"},
        )

    form = ReviewForm()
    return render(
        request,
        "members/application_detail.html",
        {
            "application": application,
            "documents": application.documents.all(),
            "shown_cnic": shown_cnic,
            "can_view_pii": can_view_pii,
            "form": form,
            "Status": MembershipApplication.Status,
        },
    )


@staff_member_test
def application_review(request: HttpRequest, pk: int) -> HttpResponse:
    application = get_object_or_404(MembershipApplication, pk=pk)
    if request.method != "POST":
        return redirect("members:application_detail", pk=pk)

    stage = request.POST.get("stage")
    if stage == "chairman":
        if not request.user.has_perm("members.approve_membership"):
            messages.error(request, _("You do not have final-approval rights."))
            return redirect("members:application_detail", pk=pk)
        try:
            profile = chairman_approve(application, request.user,
                                       fee_method=request.POST.get("fee_method", "cash"))
        except ApprovalError as exc:
            messages.error(request, str(exc))
            return redirect("members:application_detail", pk=pk)
        messages.success(
            request,
            _("Approved. Member %(num)s issued with fee receipt and ID card.")
            % {"num": profile.member_number},
        )
        return redirect("members:application_detail", pk=pk)

    # Secretary stage
    form = ReviewForm(request.POST)
    if form.is_valid():
        secretary_review(application, request.user,
                         decision=form.cleaned_data["decision"],
                         notes=form.cleaned_data["notes"])
        messages.success(request, _("Review recorded."))
    return redirect("members:application_detail", pk=pk)


@staff_member_test
def application_document(request: HttpRequest, pk: int) -> HttpResponse:
    """Stream a privately-stored identity document to a reviewer.

    Identity documents are PII (the `view_pii` permission is literally "Can view
    unmasked CNIC and identity documents"), so access is gated on it and every
    read is logged as a PII_ACCESS event — same standard as the unmasked CNIC.
    """
    document = get_object_or_404(
        ApplicationDocument.objects.select_related("application"), pk=pk
    )
    if not request.user.has_perm("members.view_pii"):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied

    from apps.core.models import AuditLog
    from apps.core.services import record_audit

    record_audit(
        AuditLog.Action.PII_ACCESS,
        "ApplicationDocument",
        document.pk,
        actor=request.user,
        metadata={"context": "document_view",
                  "application": document.application_id,
                  "doc_type": document.doc_type},
    )

    from django.http import FileResponse

    response = FileResponse(document.file.open("rb"))
    disp = "attachment" if request.GET.get("download") == "1" else "inline"
    filename = document.file.name.rsplit("/", 1)[-1]
    response["Content-Disposition"] = f'{disp}; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Member self-service + card + public verification
# ---------------------------------------------------------------------------
@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    profile = getattr(request.user, "member_profile", None)
    from apps.dues.models import DuesInvoice
    from apps.tickets.models import Ticket

    context = {"profile": profile}
    if profile:
        context["membership"] = profile.current_membership
        context["residency"] = profile.current_residency
        context["invoices"] = DuesInvoice.objects.filter(member=profile).order_by("-period_start")[:5]
        context["arrears"] = DuesInvoice.objects.filter(
            member=profile, status__in=["unpaid", "partial", "overdue"]
        ).count()
        context["card"] = getattr(profile, "card", None)
    else:
        context["application"] = (
            MembershipApplication.objects.filter(applicant_user=request.user)
            .order_by("-created_at").first()
        )
    context["tickets"] = Ticket.objects.filter(created_by=request.user).order_by("-created_at")[:5]
    return render(request, "members/dashboard.html", context)


@login_required
def my_card(request: HttpRequest) -> HttpResponse:
    profile = getattr(request.user, "member_profile", None)
    if not profile or not hasattr(profile, "card"):
        messages.info(request, _("No member card yet — your membership may still be pending."))
        return redirect("members:dashboard")
    return render(request, "members/card.html", {"profile": profile, "card": profile.card})


def card_qr(request: HttpRequest, qr_token) -> HttpResponse:
    """Render a PNG QR code that resolves to the public verification page."""
    import qrcode

    verify_url = request.build_absolute_uri(
        f"/members/verify/{qr_token}/"
    )
    img = qrcode.make(verify_url)
    response = HttpResponse(content_type="image/png")
    img.save(response, "PNG")
    return response


def verify_card(request: HttpRequest, qr_token) -> HttpResponse:
    """PUBLIC card verification — returns only minimal, non-sensitive data."""
    card = MemberCard.objects.select_related("member").filter(qr_token=qr_token).first()
    valid = bool(
        card
        and card.status == MemberCard.Status.ACTIVE
        and card.member.status == MemberProfile.Status.ACTIVE
    )
    return render(request, "members/verify.html", {"card": card, "valid": valid})


# ---------------------------------------------------------------------------
# PDF documents — fee receipt and the printable ID card
# ---------------------------------------------------------------------------
def _may_access_member(user, profile: MemberProfile) -> bool:
    """A member may fetch their own documents; staff may fetch anyone's."""
    if not user.is_authenticated:
        return False
    from apps.accounts.permissions import is_staff_member

    return is_staff_member(user) or (profile.user_id and user.id == profile.user_id)


@login_required
def fee_receipt_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    from apps.core.pdf import receipt_pdf

    payment = get_object_or_404(
        FeePayment.objects.select_related("member", "received_by"), pk=pk
    )
    if not payment.member or not _may_access_member(request.user, payment.member):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    pdf = receipt_pdf(
        title=_("Registration Fee Receipt"),
        receipt_number=payment.receipt_number,
        amount=payment.amount,
        currency=payment.currency,
        payer_label=_("Member"),
        payer_value=f"{payment.member.full_name} ({payment.member.member_number})",
        rows=[
            (_("Purpose"), _("One-time membership registration fee")),
            (_("Payment method"), payment.get_method_display()),
            (_("Reference"), payment.reference or "—"),
        ],
        issued_on=payment.paid_at,
        received_by=payment.received_by.get_full_name() if payment.received_by else "",
        verify_note=_("M.W.A.R — Reg. No. 0060, Gulshan-e-Maymar, Karachi."),
    )
    return _pdf_response(pdf, f"fee-receipt-{payment.receipt_number}.pdf",
                         download=request.GET.get("download") == "1")


@login_required
def card_pdf(request: HttpRequest) -> HttpResponse:
    from apps.core.pdf import id_card_pdf

    profile = getattr(request.user, "member_profile", None)
    if not profile or not hasattr(profile, "card"):
        messages.info(request, _("No member card yet — your membership may still be pending."))
        return redirect("members:dashboard")

    card = profile.card
    membership = profile.current_membership
    residency = profile.current_residency
    verify_url = request.build_absolute_uri(f"/members/verify/{card.qr_token}/")
    pdf = id_card_pdf(
        member_name=profile.full_name,
        member_number=card.member_number,
        membership_class=membership.get_membership_class_display() if membership else "—",
        residency=residency.get_residency_type_display() if residency else "—",
        issued_on=card.issued_at,
        expires_on=card.expires_at,
        verify_url=verify_url,
        status=card.get_status_display(),
    )
    return _pdf_response(pdf, f"mwar-card-{card.member_number}.pdf",
                         download=request.GET.get("download") == "1")
