"""Pluggable SMS gateway.

SMS is a first-class notification channel for residents (more reliable than
email). The interface is provider-agnostic; the dev backend prints to the
console. Swap ``settings.SMS_BACKEND`` for a real gateway in production.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("mwar.sms")


@dataclass
class SMSMessage:
    to: str
    body: str


class BaseSMSBackend:
    def send(self, message: SMSMessage) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleSMSBackend(BaseSMSBackend):
    """Prints the SMS instead of sending — used in dev/test."""

    def send(self, message: SMSMessage) -> bool:
        logger.info("[SMS] to=%s | %s", message.to, message.body)
        print(f"\n[FAKE SMS] → {message.to}\n  {message.body}\n")
        return True


def get_sms_backend() -> BaseSMSBackend:
    from django.conf import settings
    from django.utils.module_loading import import_string

    return import_string(settings.SMS_BACKEND)()


def send_sms(to: str, body: str) -> bool:
    return get_sms_backend().send(SMSMessage(to=to, body=body))
