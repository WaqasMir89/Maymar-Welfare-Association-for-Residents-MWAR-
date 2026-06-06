"""Public content pages + staff notice broadcasting."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.core.sms import send_sms
from apps.members.models import MemberProfile

from .models import Notice, Project


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
        sent = 0
        if notice.via_sms:
            recipients = MemberProfile.objects.filter(status="active").exclude(phone="")
            for member in recipients:
                send_sms(member.phone, f"M.W.A.R Notice: {notice.title}")
                sent += 1
        messages.success(
            request,
            _("Notice published%(sms)s.") % {"sms": f" and SMS sent to {sent} members" if sent else ""},
        )
        return redirect("content:notice_list")
    return render(request, "content/notice_create.html", {"audiences": Notice.Audience.choices})
