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

from .models import DuesInvoice
from .services import record_dues_payment


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
