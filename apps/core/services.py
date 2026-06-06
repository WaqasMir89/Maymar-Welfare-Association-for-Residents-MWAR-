"""Cross-cutting services: audit logging."""

from __future__ import annotations

from typing import Any

from .middleware import get_current_actor, get_current_ip
from .models import AuditLog


def record_audit(
    action: str,
    entity_type: str,
    entity_id: Any = "",
    *,
    metadata: dict | None = None,
    actor=None,
) -> AuditLog:
    """Write an append-only audit entry.

    Falls back to the request-scoped actor/IP when not given explicitly, so
    callers deep in the service layer don't need the request object.
    """

    return AuditLog.objects.create(
        actor=actor or get_current_actor(),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        metadata=metadata or {},
        ip=get_current_ip(),
    )
