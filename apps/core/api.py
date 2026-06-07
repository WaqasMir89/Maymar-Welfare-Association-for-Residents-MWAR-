"""Shared DRF helpers: the standard envelope, pagination, and error handler.

Implements the doc-04 contract:
  success: { "success": true, "data": … }
  list:    { "success": true, "data": [ … ], "meta": { page, page_size, total } }
  error:   { "success": false, "error": { code, message, fields? } }
"""

from __future__ import annotations

from rest_framework.pagination import PageNumberPagination
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(
            {
                "success": True,
                "data": data,
                "meta": {
                    "page": self.page.number,
                    "page_size": self.get_page_size(self.request),
                    "total": self.page.paginator.count,
                },
            }
        )


class EnvelopeJSONRenderer(JSONRenderer):
    """Wrap any not-yet-enveloped payload in the standard success envelope.

    Paginated responses already carry ``success``/``meta`` from the paginator,
    and the exception handler emits its own ``success: false`` shape — both are
    passed through untouched.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, dict) and "success" in data:
            payload = data
        else:
            payload = {"success": True, "data": data}
        return super().render(payload, accepted_media_type, renderer_context)


# Map DRF/Django exceptions to the contract's error ``code`` vocabulary.
_CODE_BY_STATUS = {
    400: "validation_error",
    401: "authentication_required",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "unprocessable",
    429: "rate_limited",
}


def envelope_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    code = _CODE_BY_STATUS.get(response.status_code, "error")
    error = {"code": code, "message": "", "fields": {}}

    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        error["message"] = str(detail["detail"])
    elif isinstance(detail, dict):
        # Field-level validation errors: {"cnic": ["Invalid CNIC format."], …}
        error["fields"] = {k: v if isinstance(v, list) else [str(v)] for k, v in detail.items()}
        error["message"] = "Validation failed."
    elif isinstance(detail, list):
        error["message"] = "; ".join(str(d) for d in detail)
    else:
        error["message"] = str(detail)

    if not error["fields"]:
        error.pop("fields")
    response.data = {"success": False, "error": error}
    return response
