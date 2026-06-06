"""Tickets: member raises/tracks; staff board manages lifecycle."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.permissions import is_staff_member, staff_member_test

from .forms import TicketForm, TicketMessageForm
from .models import Ticket


@login_required
def ticket_list(request: HttpRequest) -> HttpResponse:
    if is_staff_member(request.user):
        tickets = Ticket.objects.all()
    else:
        tickets = Ticket.objects.filter(created_by=request.user)
    status = request.GET.get("status")
    if status:
        tickets = tickets.filter(status=status)
    return render(
        request,
        "tickets/list.html",
        {"tickets": tickets.select_related("property", "assigned_to").order_by("-created_at"),
         "is_staff": is_staff_member(request.user),
         "status": status, "status_choices": Ticket.Status.choices},
    )


@login_required
def ticket_create(request: HttpRequest) -> HttpResponse:
    form = TicketForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ticket = form.save(commit=False)
        ticket.created_by = request.user
        profile = getattr(request.user, "member_profile", None)
        if profile and not ticket.property_id:
            residency = profile.current_residency
            if residency:
                ticket.property = residency.property
        ticket.save()
        messages.success(request, _("Complaint #%(n)s registered.") % {"n": ticket.ticket_number})
        return redirect("complaints:detail", pk=ticket.pk)
    return render(request, "tickets/create.html", {"form": form})


@login_required
def ticket_detail(request: HttpRequest, pk: int) -> HttpResponse:
    ticket = get_object_or_404(Ticket, pk=pk)
    staff = is_staff_member(request.user)
    if not staff and ticket.created_by_id != request.user.id:
        messages.error(request, _("You can only view your own complaints."))
        return redirect("complaints:list")

    if request.method == "POST":
        form = TicketMessageForm(request.POST)
        if form.is_valid():
            msg = form.save(commit=False)
            msg.ticket = ticket
            msg.author = request.user
            msg.is_internal = staff and bool(request.POST.get("is_internal"))
            msg.save()
            return redirect("complaints:detail", pk=pk)
    else:
        form = TicketMessageForm()

    msgs = ticket.messages.select_related("author")
    if not staff:
        msgs = msgs.filter(is_internal=False)
    return render(
        request,
        "tickets/detail.html",
        {"ticket": ticket, "messages_list": msgs, "form": form, "is_staff": staff,
         "status_choices": Ticket.Status.choices},
    )


@staff_member_test
def ticket_update_status(request: HttpRequest, pk: int) -> HttpResponse:
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status in dict(Ticket.Status.choices):
            ticket.status = new_status
            if new_status == Ticket.Status.RESOLVED:
                ticket.resolved_at = timezone.now()
            if new_status == Ticket.Status.ASSIGNED and not ticket.assigned_to_id:
                ticket.assigned_to = request.user
            ticket.save()
            messages.success(request, _("Status updated."))
    return redirect("complaints:detail", pk=pk)
