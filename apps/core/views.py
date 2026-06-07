"""Core public views: home, static info pages, health check, language switch."""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import translation
from django.views.decorators.http import require_POST

from apps.content.models import Notice, Project
from apps.members.models import MemberProfile


def home(request: HttpRequest) -> HttpResponse:
    context = {
        "projects": Project.objects.filter(is_public=True).order_by("-created_at")[:3],
        "notices": Notice.objects.filter(audience="public").order_by("-published_at")[:4],
        "member_count": MemberProfile.objects.filter(status="active").count(),
    }
    return render(request, "core/home.html", context)


def about(request: HttpRequest) -> HttpResponse:
    from apps.content.models import OrganizationProfile

    profile = OrganizationProfile.load()
    return render(request, "core/about.html", {
        "org": profile,
        "goals": profile.goals.all(),
        "milestones": profile.milestones.all(),
    })


def transparency(request: HttpRequest) -> HttpResponse:
    """Public financial transparency page."""
    from apps.dues.reports import monthly_breakdown, transparency_summary

    context = transparency_summary()
    context["monthly"] = monthly_breakdown(12)
    return render(request, "core/transparency.html", context)


def contact(request: HttpRequest) -> HttpResponse:
    return render(request, "core/contact.html")


def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness/readiness probe: verifies the database is reachable."""
    db_ok = True
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception:  # pragma: no cover - defensive
        db_ok = False
    status = 200 if db_ok else 503
    return JsonResponse({"status": "ok" if db_ok else "degraded", "db": db_ok}, status=status)


def staff_dashboard(request: HttpRequest) -> HttpResponse:
    """Analytics landing for committee/staff."""
    from django.contrib.auth.decorators import user_passes_test  # noqa

    from apps.accounts.permissions import is_staff_member
    from apps.dues.models import DuesInvoice
    from apps.dues.reports import transparency_summary
    from apps.members.models import MembershipApplication
    from apps.tickets.models import Ticket

    if not is_staff_member(request.user):
        from django.shortcuts import redirect

        return redirect("accounts:login")

    pending_apps = MembershipApplication.objects.exclude(
        status__in=["draft", "approved", "rejected"]
    ).count()
    context = {
        "member_count": MemberProfile.objects.filter(status="active").count(),
        "pending_apps": pending_apps,
        "open_tickets": Ticket.objects.exclude(status__in=["resolved", "closed"]).count(),
        "arrears": DuesInvoice.objects.filter(status__in=["unpaid", "partial", "overdue"]).count(),
        "finance": transparency_summary(),
    }
    return render(request, "core/staff_dashboard.html", context)


@require_POST
def set_language(request: HttpRequest) -> HttpResponse:
    """Switch UI language (and direction); persist to profile if logged in."""
    lang = request.POST.get("language", "en")
    if lang not in dict(settings.LANGUAGES):
        lang = "en"
    translation.activate(lang)
    if request.user.is_authenticated:
        request.user.preferred_language = lang
        request.user.save(update_fields=["preferred_language"])
    nxt = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/"
    response = redirect(nxt)
    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang)
    return response
