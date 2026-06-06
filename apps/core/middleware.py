"""Request-scoped audit context.

Stashes the current actor and client IP in a thread-local so the service
layer can write :class:`AuditLog` rows without threading ``request`` through
every function signature.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

_state = threading.local()


def get_current_actor():
    return getattr(_state, "actor", None)


def get_current_ip():
    return getattr(_state, "ip", None)


def _client_ip(request: HttpRequest) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        _state.actor = user if (user and user.is_authenticated) else None
        _state.ip = _client_ip(request)
        try:
            return self.get_response(request)
        finally:
            _state.actor = None
            _state.ip = None
