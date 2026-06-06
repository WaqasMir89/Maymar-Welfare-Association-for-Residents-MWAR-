"""Custom user model + staff office profile.

Email is the login identifier (not username). Phone is captured in Pakistani
format because SMS is a primary channel. Office title lives on a separate
``StaffProfile`` so the constitution's roles (Chairman, Secretary, …) map to
Django Groups + a human-readable title rather than a parallel auth system.
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.validators import phone_validator


class UserManager(BaseUserManager):
    """Manager keyed on email instead of username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("Superuser must have is_staff and is_superuser true")
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    class Language(models.TextChoices):
        URDU = "ur", _("اردو")
        ENGLISH = "en", _("English")

    username = None  # email is the identifier
    email = models.EmailField(_("email address"), unique=True)
    full_name = models.CharField(_("full name"), max_length=150, blank=True)
    phone = models.CharField(
        _("phone"), max_length=20, blank=True, validators=[phone_validator]
    )
    preferred_language = models.CharField(
        max_length=2, choices=Language.choices, default=Language.ENGLISH
    )
    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    def __str__(self) -> str:
        return self.full_name or self.email

    def save(self, *args, **kwargs):
        if self.full_name and not (self.first_name or self.last_name):
            parts = self.full_name.split(" ", 1)
            self.first_name = parts[0]
            self.last_name = parts[1] if len(parts) > 1 else ""
        super().save(*args, **kwargs)


class StaffProfile(models.Model):
    """Office title for committee/staff members (Chairman, Secretary, …)."""

    class Title(models.TextChoices):
        CHAIRMAN = "chairman", _("Chairman")
        SECRETARY = "secretary", _("Secretary")
        TREASURER = "treasurer", _("Treasurer / Finance Officer")
        PROJECT_MANAGER = "project_manager", _("Project Manager")
        ADMIN = "admin", _("Administrator")
        OTHER = "other", _("Other")

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    title = models.CharField(max_length=32, choices=Title.choices)
    office_phone = models.CharField(max_length=20, blank=True)

    def __str__(self) -> str:
        return f"{self.user} — {self.get_title_display()}"
