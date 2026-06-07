"""Role definitions and view-layer guards.

Roles are Django Groups; capabilities are Django Permissions (model defaults
plus a few custom ones declared in model Meta). ``view_pii`` is deliberately
*not* bundled into a role here — it is granted explicitly per the security
spec — except for the Super Administrator.
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied

# Group names (the constitution's roles).
MEMBER = "Member"
FINANCE = "Finance Officer"
PROJECT_MANAGER = "Project Manager"
SECRETARY = "Secretary"
CHAIRMAN = "Chairman"
ADMIN = "Administrator"
SUPER_ADMIN = "Super Administrator"

ALL_ROLES = [MEMBER, FINANCE, PROJECT_MANAGER, SECRETARY, CHAIRMAN, ADMIN, SUPER_ADMIN]

# Custom permission codenames (declared in the relevant model Meta.permissions).
PERM_VIEW_PII = "members.view_pii"
PERM_REVIEW_APPLICATION = "members.review_application"
PERM_APPROVE_MEMBERSHIP = "members.approve_membership"
PERM_RECORD_PAYMENT = "dues.record_payment"
PERM_BROADCAST_NOTICE = "content.broadcast_notice"
PERM_MANAGE_DOCUMENTS = "content.manage_documents"
PERM_MANAGE_ASSETS = "content.manage_assets"
PERM_APPROVE_EXPENSE = "dues.approve_expense"

# Which permissions each role receives when `setup_rbac` runs.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    MEMBER: [],
    FINANCE: [PERM_RECORD_PAYMENT, PERM_APPROVE_EXPENSE],
    PROJECT_MANAGER: [],
    SECRETARY: [PERM_REVIEW_APPLICATION, PERM_VIEW_PII, PERM_BROADCAST_NOTICE,
                PERM_MANAGE_DOCUMENTS],
    CHAIRMAN: [
        PERM_REVIEW_APPLICATION,
        PERM_APPROVE_MEMBERSHIP,
        PERM_VIEW_PII,
        PERM_BROADCAST_NOTICE,
        PERM_MANAGE_DOCUMENTS,
        PERM_MANAGE_ASSETS,
        PERM_APPROVE_EXPENSE,
    ],
    ADMIN: [
        PERM_REVIEW_APPLICATION,
        PERM_APPROVE_MEMBERSHIP,
        PERM_VIEW_PII,
        PERM_BROADCAST_NOTICE,
        PERM_MANAGE_DOCUMENTS,
        PERM_MANAGE_ASSETS,
        PERM_RECORD_PAYMENT,
        PERM_APPROVE_EXPENSE,
    ],
    SUPER_ADMIN: ["__all__"],
}


def in_group(user, *groups: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=groups).exists()


def staff_required(*groups: str):
    """Decorator: require membership in one of the given role groups."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not in_group(request.user, *groups):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def is_staff_member(user) -> bool:
    return in_group(user, FINANCE, PROJECT_MANAGER, SECRETARY, CHAIRMAN, ADMIN, SUPER_ADMIN)


def role_names(user) -> list[str]:
    """The role-group names a user belongs to (for API `me`/token claims)."""
    if not getattr(user, "is_authenticated", False):
        return []
    names = list(user.groups.values_list("name", flat=True))
    if user.is_superuser and SUPER_ADMIN not in names:
        names.append(SUPER_ADMIN)
    return names


staff_member_test = user_passes_test(is_staff_member)
