"""Public content pages + staff notice broadcasting."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.permissions import is_staff_member, staff_member_test
from apps.core.sms import send_sms
from apps.members.models import MemberProfile

from .models import Event, Notice, Notification, Project
from .services import fan_out_notice


def project_list(request: HttpRequest) -> HttpResponse:
    projects = Project.objects.filter(is_public=True)
    return render(request, "content/project_list.html", {"projects": projects})


def project_detail(request: HttpRequest, slug: str) -> HttpResponse:
    project = get_object_or_404(Project, slug=slug, is_public=True)
    return render(
        request,
        "content/project_detail.html",
        {"project": project, "updates": project.updates.filter(is_public=True)},
    )


def notice_list(request: HttpRequest) -> HttpResponse:
    notices = Notice.objects.all()
    if not request.user.is_authenticated:
        notices = notices.filter(audience=Notice.Audience.PUBLIC)
    return render(request, "content/notice_list.html", {"notices": notices})


@permission_required("content.broadcast_notice", raise_exception=True)
def notice_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        notice = Notice.objects.create(
            title=request.POST.get("title", "").strip(),
            body=request.POST.get("body", "").strip(),
            audience=request.POST.get("audience", Notice.Audience.ALL_MEMBERS),
            via_sms=bool(request.POST.get("via_sms")),
            via_email=bool(request.POST.get("via_email")),
            created_by=request.user,
        )
        delivered = fan_out_notice(notice)        # in-app inbox fan-out
        sent = 0
        if notice.via_sms:
            recipients = MemberProfile.objects.filter(status="active").exclude(phone="")
            for member in recipients:
                send_sms(member.phone, f"M.W.A.R Notice: {notice.title}")
                sent += 1
        extra = ""
        if delivered:
            extra += _(" Delivered in-app to %(n)d.") % {"n": delivered}
        if sent:
            extra += _(" SMS sent to %(n)d.") % {"n": sent}
        messages.success(request, _("Notice published.") + extra)
        return redirect("content:notice_list")
    return render(request, "content/notice_create.html", {"audiences": Notice.Audience.choices})


# ---------------------------------------------------------------------------
# In-app notifications (the bell + inbox)
# ---------------------------------------------------------------------------
@login_required
def notification_list(request: HttpRequest) -> HttpResponse:
    qs = request.user.notifications.select_related("notice")
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "content/notifications.html", {"notifications": page})


@login_required
def notification_read(request: HttpRequest, pk: int) -> HttpResponse:
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.mark_read()
    return redirect(notification.url or "content:notification_list")


@login_required
def notifications_read_all(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        request.user.notifications.filter(is_read=False).update(
            is_read=True, read_at=timezone.now()
        )
        messages.success(request, _("All notifications marked as read."))
    return redirect("content:notification_list")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def event_list(request: HttpRequest) -> HttpResponse:
    base = Event.objects.all() if request.user.is_authenticated else Event.objects.filter(is_public=True)
    now = timezone.now()
    return render(
        request,
        "content/event_list.html",
        {
            "upcoming": base.filter(starts_at__gte=now).order_by("starts_at"),
            "past": base.filter(starts_at__lt=now).order_by("-starts_at")[:10],
            "can_manage": is_staff_member(request.user),
        },
    )


def event_detail(request: HttpRequest, pk: int) -> HttpResponse:
    qs = Event.objects.all() if request.user.is_authenticated else Event.objects.filter(is_public=True)
    event = get_object_or_404(qs, pk=pk)
    return render(request, "content/event_detail.html", {"event": event})


@staff_member_test
def event_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        starts = request.POST.get("starts_at")
        if not request.POST.get("title", "").strip() or not starts:
            messages.error(request, _("A title and start time are required."))
            return redirect("content:event_create")
        event = Event.objects.create(
            title=request.POST.get("title", "").strip(),
            description=request.POST.get("description", "").strip(),
            starts_at=starts,
            ends_at=request.POST.get("ends_at") or None,
            location=request.POST.get("location", "").strip(),
            is_public=bool(request.POST.get("is_public")),
        )
        messages.success(request, _("Event created."))
        return redirect("content:event_detail", pk=event.pk)
    return render(request, "content/event_form.html", {})
