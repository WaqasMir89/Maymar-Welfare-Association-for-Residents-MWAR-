"""Locality registry: Sector → Sub-Sector → Property.

This is the authoritative spatial backbone of the association. Every
membership and every dues invoice ultimately hangs off a Property here.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class Sector(TimeStampedModel):
    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=16, unique=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name


class SubSector(TimeStampedModel):
    sector = models.ForeignKey(Sector, on_delete=models.CASCADE, related_name="sub_sectors")
    name = models.CharField(max_length=80)
    code = models.CharField(max_length=16)

    class Meta:
        ordering = ["sector__code", "code"]
        constraints = [
            models.UniqueConstraint(fields=["sector", "code"], name="uniq_subsector_code"),
        ]

    def __str__(self) -> str:
        return f"{self.sector.code}-{self.code}"


class Property(TimeStampedModel):
    """A house/plot — the unit of the association."""

    class Type(models.TextChoices):
        HOUSE = "house", _("House")
        PLOT = "plot", _("Plot")
        APARTMENT = "apartment", _("Apartment")
        COMMERCIAL = "commercial", _("Commercial")

    class Status(models.TextChoices):
        OCCUPIED = "occupied", _("Occupied")
        VACANT = "vacant", _("Vacant")
        UNDER_CONSTRUCTION = "under_construction", _("Under construction")

    sub_sector = models.ForeignKey(SubSector, on_delete=models.PROTECT, related_name="properties")
    house_number = models.CharField(max_length=32)
    property_type = models.CharField(max_length=16, choices=Type.choices, default=Type.HOUSE)
    street = models.CharField(max_length=120, blank=True)
    full_address = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OCCUPIED)

    class Meta:
        ordering = ["sub_sector", "house_number"]
        verbose_name_plural = "properties"
        constraints = [
            models.UniqueConstraint(
                fields=["sub_sector", "house_number"], name="uniq_property_house"
            ),
        ]
        indexes = [models.Index(fields=["house_number"])]

    def __str__(self) -> str:
        return self.display_address

    @property
    def sector(self) -> Sector:
        return self.sub_sector.sector

    @property
    def display_address(self) -> str:
        if self.full_address:
            return self.full_address
        return f"House {self.house_number}, {self.sub_sector}, Gulshan-e-Maymar"

    def save(self, *args, **kwargs):
        if not self.full_address:
            self.full_address = (
                f"House {self.house_number}, Sub-Sector {self.sub_sector.code}, "
                f"Sector {self.sub_sector.sector.code}, Gulshan-e-Maymar, Karachi"
            )
        super().save(*args, **kwargs)
