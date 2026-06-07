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

from .models import Donation, DuesInvoice, Expense
from .services import create_expense, decide_expense, record_donation, record_dues_payment


@staff_member_test
def billing_board(request: HttpRequest) -> HttpResponse:
    qs = DuesInvoice.objects.select_related("property__sub_sector", "member", "plan")
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
        DuesInvoice.objects.filter(member=profile).select_related("plan", "property")
        if profile else DuesInvoice.objects.none()
    )
    return render(request, "dues/my_dues.html", {"invoices": invoices.order_by("-period_start")})


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
