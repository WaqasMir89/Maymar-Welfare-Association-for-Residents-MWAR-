"""Inject brand identity + active text direction into every template."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from django.utils import translation

BRAND = {
    "name": "Maymar Welfare Association for Residents",
    "name_ur": "معمار ویلفیئر ایسوسی ایشن برائے ریزیڈنٹس",
    "short": "M.W.A.R",
    "reg_no": "0060",
    "locality": "Gulshan-e-Maymar, Karachi",
    "tagline": "Hands of Hope",
}


def brand(request: HttpRequest) -> dict:
    from apps.accounts.permissions import is_staff_member

    lang = translation.get_language() or "en"
    return {
        "brand": BRAND,
        "is_rtl": lang.startswith("ur"),
        "active_lang": lang,
        "currency": settings.CURRENCY,
        # Group-based staff check (not the is_staff flag) — drives the Staff nav
        # link so every committee role (incl. Finance Officer) can reach it.
        "is_staff_member": (
            is_staff_member(request.user) if getattr(request, "user", None) is not None else False
        ),
    }
