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

from .models import Event, Notice, Notification, OrganizationAsset, Project, PublicDocument
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


# ---------------------------------------------------------------------------
# Public document library — staff upload PDFs, anyone downloads
# ---------------------------------------------------------------------------
def document_list(request: HttpRequest) -> HttpResponse:
    documents = PublicDocument.objects.filter(is_published=True)
    can_manage = request.user.has_perm("content.manage_documents")
    if can_manage:                       # managers also see unpublished drafts
        documents = PublicDocument.objects.all()
    # Group by category for display, preserving the human-readable label.
    groups: dict[str, dict] = {}
    for doc in documents:
        groups.setdefault(doc.category, {"label": doc.get_category_display(), "items": []})
        groups[doc.category]["items"].append(doc)
    return render(
        request,
        "content/document_list.html",
        {"groups": groups.values(), "can_manage": can_manage},
    )


def document_download(request: HttpRequest, pk: int) -> HttpResponse:
    """Public PDF download. Unpublished drafts are reachable only by managers."""
    qs = PublicDocument.objects.all()
    if not request.user.has_perm("content.manage_documents"):
        qs = qs.filter(is_published=True)
    document = get_object_or_404(qs, pk=pk)

    from django.http import FileResponse

    response = FileResponse(document.file.open("rb"), content_type="application/pdf")
    filename = document.file.name.rsplit("/", 1)[-1]
    disp = "inline" if request.GET.get("inline") == "1" else "attachment"
    response["Content-Disposition"] = f'{disp}; filename="{filename}"'
    return response


@login_required
def document_upload(request: HttpRequest) -> HttpResponse:
    # Logged-in users without the permission get a friendly nudge rather than a
    # bare 403; anonymous users are sent to login by @login_required first.
    if not request.user.has_perm("content.manage_documents"):
        messages.error(request, _("You don't have permission to upload documents."))
        return redirect("content:document_list")
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        upload = request.FILES.get("file")
        if not title or not upload:
            messages.error(request, _("A title and a PDF file are required."))
            return redirect("content:document_upload")
        name = (upload.name or "").lower()
        if not name.endswith(".pdf") or upload.content_type not in (
            "application/pdf", "application/x-pdf", "application/octet-stream"
        ):
            messages.error(request, _("Only PDF files can be uploaded."))
            return redirect("content:document_upload")
        document = PublicDocument(
            title=title,
            description=request.POST.get("description", "").strip(),
            category=request.POST.get("category", PublicDocument.Category.OTHER),
            file=upload,
            is_published=bool(request.POST.get("is_published")),
            uploaded_by=request.user,
        )
        try:
            document.full_clean()        # runs the FileExtensionValidator too
        except Exception:
            messages.error(request, _("Only PDF files can be uploaded."))
            return redirect("content:document_upload")
        document.save()
        messages.success(request, _("Document uploaded."))
        return redirect("content:document_list")
    return render(
        request,
        "content/document_form.html",
        {"categories": PublicDocument.Category.choices},
    )


# ---------------------------------------------------------------------------
# Organization assets — senior staff add, public views
# ---------------------------------------------------------------------------
def asset_list(request: HttpRequest) -> HttpResponse:
    can_manage = request.user.has_perm("content.manage_assets")
    assets = OrganizationAsset.objects.all() if can_manage else OrganizationAsset.objects.filter(is_public=True)
    groups: dict[str, dict] = {}
    for asset in assets:
        groups.setdefault(asset.category, {"label": asset.get_category_display(), "items": []})
        groups[asset.category]["items"].append(asset)
    total_value = sum(
        (a.estimated_value or 0) for a in assets if a.estimated_value is not None
    )
    return render(request, "content/asset_list.html", {
        "groups": groups.values(), "can_manage": can_manage, "total_value": total_value,
    })


@permission_required("content.manage_assets", raise_exception=True)
def asset_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, _("An asset name is required."))
            return redirect("content:asset_create")
        value = request.POST.get("estimated_value") or None
        asset = OrganizationAsset(
            name=name,
            category=request.POST.get("category", OrganizationAsset.Category.OTHER),
            description=request.POST.get("description", "").strip(),
            location=request.POST.get("location", "").strip(),
            quantity=request.POST.get("quantity") or 1,
            estimated_value=value,
            acquired_on=request.POST.get("acquired_on") or None,
            photo=request.FILES.get("photo"),
            is_public=bool(request.POST.get("is_public")),
            added_by=request.user,
        )
        try:
            asset.full_clean()
        except Exception as exc:
            messages.error(request, _("Please check the asset details: %(e)s") % {"e": exc})
            return redirect("content:asset_create")
        asset.save()
        messages.success(request, _("Asset added to the register."))
        return redirect("content:asset_list")
    return render(request, "content/asset_form.html", {
        "categories": OrganizationAsset.Category.choices,
    })


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
