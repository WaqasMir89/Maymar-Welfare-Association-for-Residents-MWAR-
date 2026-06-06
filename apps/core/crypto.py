"""Field-level encryption + lookup hashing for sensitive PII (CNIC).

CNIC numbers are encrypted at rest with Fernet (AES-128-CBC + HMAC). A
separate salted SHA-256 hash is stored alongside so uniqueness and lookup
work without ever decrypting. The Fernet key is derived from
``settings.CNIC_ENCRYPTION_KEY`` so operators can supply any passphrase.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    raw = settings.CNIC_ENCRYPTION_KEY.encode("utf-8")
    # Derive a stable 32-byte urlsafe key from whatever passphrase is supplied.
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def blind_hash(value: str) -> str:
    """Deterministic, salted hash for uniqueness/lookups (not reversible)."""

    salted = f"{settings.SECRET_KEY}:{value}".encode("utf-8")
    return hashlib.sha256(salted).hexdigest()


def mask_cnic(cnic: str) -> str:
    """Mask a CNIC for display: ``*****-*****34-*`` style.

    Reveals only the two digits before the final check digit, matching the
    masking pattern in the security spec.
    """

    digits = [c for c in cnic if c.isdigit()]
    if len(digits) != 13:
        return "*****-*******-*"
    tail = "".join(digits[10:12])
    return f"*****-*****{tail}-*"
