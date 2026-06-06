"""Custom model fields for sensitive data."""

from __future__ import annotations

from django.db import models

from . import crypto


class EncryptedCharField(models.TextField):
    """Transparently Fernet-encrypts its value at rest.

    Stored as ciphertext text; returns plaintext to Python. Pair with a
    separate hash column (see ``crypto.blind_hash``) for uniqueness/lookups,
    since ciphertext is non-deterministic and can't be indexed for equality.
    """

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        return crypto.encrypt(str(value))

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        return crypto.decrypt(value)

    def to_python(self, value):
        return value
