"""Dues views: staff billing board + record payment; member self-service."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.accounts.permissions import staff_member_test

from .models import Donation, DuesInvoice, DuesPayment, Expense, PaymentSubmission
from .services import (
    create_expense,
    create_payment_submission,
    decide_expense,
    record_donation,
    record_dues_payment,
    reject_payment_submission,
    verify_payment_submission,
)


def _pdf_response(data: bytes, filename: str, *, download: bool = False) -> HttpResponse:
    response = HttpResponse(data, content_type="application/pdf")
    disp = "attachment" if download else "inline"
    response["Content-Disposition"] = f'{disp}; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Finance dashboard + downloadable reports
# ---------------------------------------------------------------------------
@staff_member_test
def finance_dashboard(request: HttpRequest) -> HttpResponse:
    from apps.dues.reports import finance_dashboard as _data

    return render(request, "dues/finance_dashboard.html", _data())


@staff_member_test
def export_pending_dues(request: HttpRequest) -> HttpResponse:
    from apps.core.exports import csv_response

    qs = (DuesInvoice.objects
          .filter(status__in=["unpaid", "partial", "overdue"])
          .select_related("property", "member", "plan")
          .order_by("due_date"))
    rows = ([inv.property, inv.member.full_name if inv.member else "—", inv.plan.name,
             inv.period_start, inv.amount_due, inv.amount_paid, inv.balance,
             inv.due_date, inv.get_status_display()] for inv in qs)
    return csv_response(
        "pending-dues.csv",
        ["Property", "Member", "Plan", "Period", "Amount due", "Amount paid",
         "Balance", "Due date", "Status"],
        rows,
    )


@staff_member_test
def export_monthly_finance(request: HttpRequest) -> HttpResponse:
    from apps.core.exports import csv_response
    from apps.dues.reports import monthly_breakdown

    rows = ([r["label"], r["dues"], r["donations"], r["collected"], r["spent"], r["net"]]
            for r in monthly_breakdown(12))
    return csv_response(
        "monthly-finance.csv",
        ["Month", "Dues collected", "Donations", "Total collected", "Spent", "Net"],
        rows,
    )


def export_public_finance(request: HttpRequest) -> HttpResponse:
    """Public, PII-free month-wise collection vs spending report."""
    from apps.core.exports import csv_response
    from apps.dues.reports import monthly_breakdown

    rows = ([r["label"], r["collected"], r["spent"], r["net"]]
            for r in monthly_breakdown(12))
    return csv_response(
        "mwar-collection-and-spending.csv",
        ["Month", "Collected (PKR)", "Spent (PKR)", "Net (PKR)"],
        rows,
    )


def _ledger_filters(request):
    """Parse the shared transaction-ledger filters from the query string."""
    from datetime import date

    def _date(name):
        raw = request.GET.get(name)
        try:
            return date.fromisoformat(raw) if raw else None
        except ValueError:
            return None

    return {
        "kind": request.GET.get("kind") or None,
        "direction": request.GET.get("direction") or None,
        "start": _date("start"),
        "end": _date("end"),
        "search": request.GET.get("q", ""),
    }


@staff_member_test
def transaction_ledger(request: HttpRequest) -> HttpResponse:
    """Line-by-line ledger of every money movement — not just summaries."""
    from apps.dues.reports import ledger_totals, transaction_ledger as _ledger

    filters = _ledger_filters(request)
    rows = _ledger(**filters)
    totals = ledger_totals(rows)
    page = Paginator(rows, 50).get_page(request.GET.get("page"))

    querystring = request.GET.copy()
    querystring.pop("page", None)
    return render(request, "dues/transactions.html", {
        "transactions": page, "totals": totals, "filters": filters,
        "querystring": querystring.urlencode(),
        "kinds": [("dues", _("Dues payment")), ("fee", _("Registration fee")),
                  ("donation", _("Donation")), ("expense", _("Expense"))],
    })


@staff_member_test
def export_transactions(request: HttpRequest) -> HttpResponse:
    from apps.core.exports import csv_response
    from apps.dues.reports import transaction_ledger as _ledger

    rows = _ledger(**_ledger_filters(request))

    def _out():
        for r in rows:
            d = r["date"]
            yield [d.strftime("%Y-%m-%d"), r["kind_label"],
                   "IN" if r["direction"] == "in" else "OUT",
                   r["party"], r["detail"],
                   r["amount"] if r["direction"] == "in" else "",
                   r["amount"] if r["direction"] == "out" else "",
                   r["method"], r["reference"], r["receipt"],
                   r["recorded_by"].get_full_name() if r["recorded_by"] else ""]

    return csv_response(
        "transactions.csv",
        ["Date", "Type", "Direction", "Party", "Detail", "Money in", "Money out",
         "Method/Status", "Reference", "Receipt", "Recorded by"],
        _out(),
    )


@staff_member_test
def billing_board(request: HttpRequest) -> HttpResponse:
    qs = DuesInvoice.objects.select_related(
        "property__sub_sector", "member", "plan"
    ).prefetch_related("payments")
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    page = Paginator(qs.order_by("-period_start", "property__house_number"), 25).get_page(
        request.GET.get("page")
    )
    totals = qs.aggregate(billed=Sum("amount_due"), paid=Sum("amount_paid"))
    return render(
        request,
        "dues/billing_board.html",
        {"invoices": page, "totals": totals, "status": status,
         "status_choices": DuesInvoice.Status.choices},
    )


@permission_required("dues.record_payment", raise_exception=True)
def record_payment(request: HttpRequest, pk: int) -> HttpResponse:
    invoice = get_object_or_404(DuesInvoice, pk=pk)
    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount", "0"))
        except InvalidOperation:
            amount = Decimal("0")
        if amount <= 0:
            messages.error(request, _("Enter a valid amount."))
            return redirect("dues:record_payment", pk=pk)
        payment = record_dues_payment(
            invoice,
            amount=amount,
            method=request.POST.get("method", "cash"),
            user=request.user,
            reference=request.POST.get("reference", ""),
            idempotency_key=request.POST.get("idempotency_key", ""),
        )
        messages.success(request, _("Payment recorded. Receipt %(r)s.") % {"r": payment.receipt_number})
        return redirect("dues:billing_board")
    return render(request, "dues/record_payment.html", {"invoice": invoice})


@login_required
def my_dues(request: HttpRequest) -> HttpResponse:
    profile = getattr(request.user, "member_profile", None)
    invoices = (
        DuesInvoice.objects.filter(member=profile)
        .select_related("plan", "property").prefetch_related("payments")
        if profile else DuesInvoice.objects.none()
    )
    return render(request, "dues/my_dues.html", {"invoices": invoices.order_by("-period_start")})


def _outstanding_invoices(profile):
    return list(
        DuesInvoice.objects.filter(
            member=profile,
            status__in=[DuesInvoice.Status.UNPAID, DuesInvoice.Status.PARTIAL,
                        DuesInvoice.Status.OVERDUE],
        ).select_related("plan", "property").order_by("period_start")
    )


@login_required
def pay_dues(request: HttpRequest) -> HttpResponse:
    """Member 'pay everything in one click' page with proof-of-payment upload."""
    from django.conf import settings

    profile = getattr(request.user, "member_profile", None)
    if not profile:
        messages.info(request, _("You don't have an approved membership yet."))
        return redirect("members:dashboard")

    invoices = [inv for inv in _outstanding_invoices(profile) if inv.balance > 0]
    dues_total = sum((inv.balance for inv in invoices), Decimal("0"))
    registration_due = (
        Decimal(settings.REGISTRATION_FEE) if not profile.fee_payments.exists() else Decimal("0")
    )
    pending = profile.payment_submissions.filter(
        status=PaymentSubmission.Status.PENDING
    ).first()

    if request.method == "POST":
        proof = request.FILES.get("proof")
        if not proof:
            messages.error(request, _("Please attach a proof of payment (image or PDF)."))
            return redirect("dues:pay_dues")
        name = (proof.name or "").lower()
        if not name.endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp")):
            messages.error(request, _("Proof must be a PDF or an image (JPG, PNG, WEBP)."))
            return redirect("dues:pay_dues")

        include_registration = bool(request.POST.get("include_registration")) and registration_due > 0
        try:
            donation_amount = Decimal(request.POST.get("donation_amount") or "0")
        except (InvalidOperation, TypeError):
            donation_amount = Decimal("0")
        if donation_amount < 0:
            donation_amount = Decimal("0")

        reg_amount = registration_due if include_registration else Decimal("0")
        total = dues_total + reg_amount + donation_amount
        if total <= 0:
            messages.error(request, _("There is nothing to pay. Add a donation amount or wait for the next invoice."))
            return redirect("dues:pay_dues")

        submission = create_payment_submission(
            member=profile, user=request.user, invoices=invoices,
            pays_registration=include_registration, registration_amount=reg_amount,
            donation_amount=donation_amount, method=request.POST.get("method", "bank_transfer"),
            reference=request.POST.get("reference", ""), proof=proof,
            note=request.POST.get("note", ""),
        )
        messages.success(
            request,
            _("Payment of Rs %(amt)s submitted for verification. You'll be notified once confirmed.")
            % {"amt": f"{submission.total_amount:.0f}"},
        )
        return redirect("dues:my_dues")

    return render(request, "dues/pay_dues.html", {
        "invoices": invoices,
        "dues_total": dues_total,
        "registration_due": registration_due,
        "grand_total": dues_total + registration_due,
        "pending": pending,
        "methods": PaymentSubmission._meta.get_field("method").choices,
    })


def _may_access_submission(user, submission) -> bool:
    if not user.is_authenticated:
        return False
    return user.has_perm("dues.record_payment") or (
        submission.member.user_id and user.id == submission.member.user_id
    )


@login_required
def proof_download(request: HttpRequest, pk: int) -> HttpResponse:
    """Serve a payment proof to its owner or to Finance staff."""
    submission = get_object_or_404(PaymentSubmission.objects.select_related("member"), pk=pk)
    if not _may_access_submission(request.user, submission):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    from django.http import FileResponse

    response = FileResponse(submission.proof.open("rb"))
    response["Content-Disposition"] = (
        f'inline; filename="{submission.proof.name.rsplit("/", 1)[-1]}"'
    )
    return response


@permission_required("dues.record_payment", raise_exception=True)
def submission_queue(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status", PaymentSubmission.Status.PENDING)
    qs = PaymentSubmission.objects.select_related("member", "reviewed_by")
    if status:
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    status_tabs = [
        (s, label, PaymentSubmission.objects.filter(status=s).count())
        for s, label in PaymentSubmission.Status.choices
    ]
    return render(request, "dues/submission_queue.html", {
        "submissions": page, "status": status, "status_tabs": status_tabs,
    })


@permission_required("dues.record_payment", raise_exception=True)
def submission_decide(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(PaymentSubmission, pk=pk)
    if request.method == "POST":
        if request.POST.get("decision") == "verify":
            verify_payment_submission(submission, user=request.user)
            messages.success(request, _("Payment verified and posted to the ledger."))
        else:
            reject_payment_submission(submission, user=request.user,
                                      reason=request.POST.get("reason", ""))
            messages.info(request, _("Payment submission rejected."))
    return redirect("dues:submission_queue")


# ---------------------------------------------------------------- donations --
@staff_member_test
def donation_list(request: HttpRequest) -> HttpResponse:
    qs = Donation.objects.select_related("donor_member", "received_by")
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    total = qs.aggregate(s=Sum("amount"))["s"]
    return render(request, "dues/donations.html", {"donations": page, "total": total})


@permission_required("dues.record_payment", raise_exception=True)
def record_donation_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount", "0"))
        except InvalidOperation:
            amount = Decimal("0")
        donor = request.POST.get("donor_name", "").strip()
        if amount <= 0 or not donor:
            messages.error(request, _("Enter a donor name and a valid amount."))
            return redirect("dues:record_donation")
        donation = record_donation(
            donor_name=donor,
            amount=amount,
            user=request.user,
            method=request.POST.get("method", "cash"),
            purpose=request.POST.get("purpose", ""),
            reference=request.POST.get("reference", ""),
            is_public=request.POST.get("is_public") == "on",
        )
        messages.success(request, _("Donation recorded. Receipt %(r)s.") % {"r": donation.receipt_number})
        return redirect("dues:donation_list")
    return render(request, "dues/record_donation.html", {})


# ----------------------------------------------------------------- expenses --
@staff_member_test
def expense_list(request: HttpRequest) -> HttpResponse:
    qs = Expense.objects.select_related("requested_by", "approved_by")
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    pending = Expense.objects.filter(status=Expense.Status.PENDING).aggregate(s=Sum("amount"))["s"]
    approved = Expense.objects.filter(
        status__in=[Expense.Status.APPROVED, Expense.Status.PAID]
    ).aggregate(s=Sum("amount"))["s"]
    return render(
        request,
        "dues/expenses.html",
        {"expenses": page, "status": status, "pending_total": pending,
         "approved_total": approved, "status_choices": Expense.Status.choices,
         "can_approve": request.user.has_perm("dues.approve_expense")},
    )


@permission_required("dues.record_payment", raise_exception=True)
def expense_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount", "0"))
        except InvalidOperation:
            amount = Decimal("0")
        category = request.POST.get("category", "").strip()
        if amount <= 0 or not category:
            messages.error(request, _("Enter a category and a valid amount."))
            return redirect("dues:expense_create")
        expense = create_expense(
            category=category,
            amount=amount,
            user=request.user,
            description=request.POST.get("description", ""),
            incurred_on=request.POST.get("incurred_on") or None,
            attachment=request.FILES.get("attachment"),
        )
        messages.success(request, _("Expense #%(id)s logged, pending approval.") % {"id": expense.pk})
        return redirect("dues:expense_list")
    return render(request, "dues/expense_form.html", {})


@permission_required("dues.approve_expense", raise_exception=True)
def expense_decide(request: HttpRequest, pk: int) -> HttpResponse:
    expense = get_object_or_404(Expense, pk=pk)
    if request.method == "POST":
        approve = request.POST.get("decision") == "approve"
        decide_expense(expense, approve=approve, user=request.user)
        messages.success(
            request,
            _("Expense #%(id)s %(d)s.") % {"id": expense.pk, "d": expense.get_status_display().lower()},
        )
    return redirect("dues:expense_list")


# ------------------------------------------------------------ PDF receipts --
@login_required
def dues_receipt_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    from apps.core.pdf import receipt_pdf

    payment = get_object_or_404(
        DuesPayment.objects.select_related("invoice__property", "invoice__member", "received_by"),
        pk=pk,
    )
    member = payment.invoice.member
    from apps.accounts.permissions import is_staff_member

    owns = member and member.user_id and request.user.id == member.user_id
    if not (is_staff_member(request.user) or owns):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    inv = payment.invoice
    pdf = receipt_pdf(
        title=_("Maintenance Dues Receipt"),
        receipt_number=payment.receipt_number,
        amount=payment.amount,
        currency="PKR",
        payer_label=_("Property"),
        payer_value=str(inv.property),
        rows=[
            (_("Member"), member.full_name if member else "—"),
            (_("Billing period"), inv.period_start.strftime("%B %Y")),
            (_("Payment method"), payment.get_method_display()),
            (_("Reference"), payment.reference or "—"),
            (_("Invoice balance"), f"PKR {inv.balance:,.0f}"),
        ],
        issued_on=payment.paid_at,
        received_by=payment.received_by.get_full_name() if payment.received_by else "",
        verify_note=_("M.W.A.R — Reg. No. 0060, Gulshan-e-Maymar, Karachi."),
    )
    return _pdf_response(pdf, f"dues-receipt-{payment.receipt_number}.pdf",
                         download=request.GET.get("download") == "1")


@staff_member_test
def donation_receipt_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    from apps.core.pdf import receipt_pdf

    donation = get_object_or_404(Donation.objects.select_related("received_by"), pk=pk)
    pdf = receipt_pdf(
        title=_("Donation Receipt"),
        receipt_number=donation.receipt_number,
        amount=donation.amount,
        currency=donation.currency,
        payer_label=_("Donor"),
        payer_value=donation.donor_name,
        rows=[
            (_("Purpose"), donation.purpose or _("General fund")),
            (_("Payment method"), donation.get_method_display()),
            (_("Reference"), donation.reference or "—"),
        ],
        issued_on=donation.donated_at,
        received_by=donation.received_by.get_full_name() if donation.received_by else "",
        verify_note=_("Thank you for supporting M.W.A.R — “Hands of Hope”."),
    )
    return _pdf_response(pdf, f"donation-receipt-{donation.receipt_number}.pdf",
                         download=request.GET.get("download") == "1")
