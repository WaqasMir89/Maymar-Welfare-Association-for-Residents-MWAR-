from django.contrib import admin

from .models import Property, Sector, SubSector


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "description")
    search_fields = ("code", "name")


@admin.register(SubSector)
class SubSectorAdmin(admin.ModelAdmin):
    list_display = ("__str__", "sector", "name")
    list_filter = ("sector",)


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("house_number", "sub_sector", "property_type", "status")
    list_filter = ("status", "property_type", "sub_sector__sector")
    search_fields = ("house_number", "full_address")
