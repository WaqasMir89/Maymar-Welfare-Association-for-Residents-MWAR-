"""Staff-facing property registry browser."""

from __future__ import annotations

from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.accounts.permissions import staff_member_test

from .models import Property, Sector


@staff_member_test
def property_list(request: HttpRequest) -> HttpResponse:
    qs = Property.objects.select_related("sub_sector__sector")
    sector = request.GET.get("sector")
    status = request.GET.get("status")
    search = request.GET.get("search")
    if sector:
        qs = qs.filter(sub_sector__sector__code=sector)
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(house_number__icontains=search)

    page = Paginator(qs.order_by("sub_sector", "house_number"), 25).get_page(
        request.GET.get("page")
    )
    context = {
        "properties": page,
        "sectors": Sector.objects.annotate(n=Count("sub_sectors__properties")),
        "total": qs.count(),
        "filters": {"sector": sector, "status": status, "search": search},
        "status_choices": Property.Status.choices,
    }
    return render(request, "locality/property_list.html", context)
