"""Locality API: sectors, sub-sectors, and the property registry."""

from __future__ import annotations

from rest_framework import serializers, viewsets

from .models import Property, Sector, SubSector


class SubSectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubSector
        fields = ["id", "name", "code", "sector"]


class SectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sector
        fields = ["id", "name", "code"]


class PropertySerializer(serializers.ModelSerializer):
    display_address = serializers.CharField(read_only=True)
    sector = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = ["id", "house_number", "sub_sector", "sector", "status", "display_address"]

    def get_sector(self, obj) -> int:
        return obj.sub_sector.sector_id


class SectorViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SectorSerializer
    queryset = Sector.objects.order_by("code")


class PropertyViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PropertySerializer
    search_fields = ["house_number"]

    def get_queryset(self):
        qs = Property.objects.select_related("sub_sector__sector")
        p = self.request.query_params
        if p.get("sector"):
            qs = qs.filter(sub_sector__sector_id=p["sector"])
        if p.get("sub_sector"):
            qs = qs.filter(sub_sector_id=p["sub_sector"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("search"):
            qs = qs.filter(house_number__icontains=p["search"])
        return qs.order_by("sub_sector", "house_number")
