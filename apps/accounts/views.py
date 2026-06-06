"""Authentication views (server-rendered)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login, logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import translation
from django.utils.translation import gettext as _

from apps.core.models import AuditLog
from apps.core.services import record_audit

from .forms import EmailLoginForm, RegistrationForm


def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("core:home")
    form = EmailLoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        translation.activate(user.preferred_language)
        record_audit(AuditLog.Action.LOGIN, "User", user.pk, actor=user)
        messages.success(request, _("Welcome back."))
        return redirect(request.GET.get("next") or "core:home")
    return render(request, "accounts/login.html", {"form": form})


def register_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("core:home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        record_audit(AuditLog.Action.CREATE, "User", user.pk, actor=user)
        messages.success(request, _("Account created. Welcome to M.W.A.R."))
        return redirect("core:home")
    return render(request, "accounts/register.html", {"form": form})


def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    messages.info(request, _("You have been signed out."))
    return redirect("core:home")
