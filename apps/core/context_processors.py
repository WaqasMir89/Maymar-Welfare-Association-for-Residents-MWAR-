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
    lang = translation.get_language() or "en"
    return {
        "brand": BRAND,
        "is_rtl": lang.startswith("ur"),
        "active_lang": lang,
        "currency": settings.CURRENCY,
    }
