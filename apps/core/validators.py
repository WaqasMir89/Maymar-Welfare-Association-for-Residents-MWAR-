"""Pakistani-context validators: CNIC and phone numbers."""

from __future__ import annotations

from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

# National Identity Card: 13 digits as #####-#######-#
cnic_validator = RegexValidator(
    regex=r"^\d{5}-\d{7}-\d$",
    message=_("Enter a valid CNIC in the format 42101-1234567-1."),
)

# Pakistani mobile/landline, accepting +92 / 0092 / 0 prefixes.
phone_validator = RegexValidator(
    regex=r"^(?:\+92|0092|0)?3\d{2}[-\s]?\d{7}$|^(?:\+92|0092|0)?\d{2,4}[-\s]?\d{6,8}$",
    message=_("Enter a valid Pakistani phone number, e.g. 0301-2345678."),
)
