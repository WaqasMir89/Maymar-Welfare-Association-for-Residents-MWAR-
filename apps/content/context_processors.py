"""Expose the unread-notification count to every template (the nav bell badge)."""

from __future__ import annotations

from django.http import HttpRequest


def notifications(request: HttpRequest) -> dict:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"unread_notifications": 0}
    return {"unread_notifications": user.notifications.filter(is_read=False).count()}
