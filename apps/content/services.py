"""Content services: notice fan-out to per-user in-app notifications."""

from __future__ import annotations

from .models import Notice, Notification


def notify(recipient, *, title, body="", url="", level=Notification.Level.INFO, notice=None):
    """Create a single in-app notification."""
    return Notification.objects.create(
        recipient=recipient, title=title, body=body, url=url, level=level, notice=notice
    )


def _recipients(notice: Notice):
    """The User accounts a notice reaches in-app.

    Members are the audience, but staff are part of the association and also see
    association-wide notices — important because not every member has a login yet.
    """
    from apps.accounts.models import User

    if notice.audience == Notice.Audience.SECTOR and notice.sector_id:
        return User.objects.filter(
            member_profile__status="active",
            member_profile__residencies__is_current=True,
            member_profile__residencies__property__sub_sector__sector_id=notice.sector_id,
        ).distinct()

    members = User.objects.filter(member_profile__status="active")
    staff = User.objects.filter(is_staff=True)
    return (members | staff).distinct()


def fan_out_notice(notice: Notice) -> int:
    """Create an in-app Notification per recipient. Returns the count created."""
    if not notice.via_in_app:
        return 0
    recipients = list(_recipients(notice))
    Notification.objects.bulk_create([
        Notification(
            recipient=user,
            title=notice.title,
            body=notice.body,
            url=f"/content/notices/#notice-{notice.pk}",
            level=Notification.Level.INFO,
            notice=notice,
        )
        for user in recipients
    ])
    return len(recipients)
