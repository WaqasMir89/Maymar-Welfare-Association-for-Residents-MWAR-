"""Small helpers for streaming CSV report downloads."""

from __future__ import annotations

import csv
from typing import Iterable, Sequence

from django.http import HttpResponse


def csv_response(filename: str, header: Sequence[str], rows: Iterable[Sequence]) -> HttpResponse:
    """Build a downloadable CSV. ``filename`` is the suggested download name."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")              # BOM so Excel renders Urdu/UTF-8 correctly
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return response
