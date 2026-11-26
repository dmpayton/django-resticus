import sys
import traceback

from django import http
from django.conf import settings
from django.utils.functional import Promise
from django.utils.translation import gettext as _

from .settings import api_settings

__all__ = [
    "JSONResponse",
    "StreamingJSONResponse",
    "JSONErrorResponse",
    "Http200",
    "Http201",
    "Http204",
    "Http400",
    "Http401",
    "Http403",
    "Http404",
    "Http405",
    "Http409",
    "Http500",
]

HTTP_HEADER_ENCODING = "iso-8859-1"


class JSONResponse(http.HttpResponse):
    """An HTTP response class that consumes data to be serialized to JSON."""

    def __init__(self, data, **kwargs):
        kwargs.setdefault("content_type", "application/json")
        data = api_settings.JSON_ENCODER().encode(data).encode("utf-8")
        super().__init__(content=data, **kwargs)


class StreamingJSONResponse(http.StreamingHttpResponse):
    def __init__(self, data, **kwargs):
        kwargs.setdefault("content_type", "application/json")
        data = api_settings.JSON_ENCODER().iterencode(data)
        super().__init__(streaming_content=data, **kwargs)


class JSONErrorResponse(JSONResponse):
    """A JSON response class for simple API errors."""

    default_reason = None
    status_code = 500

    def __init__(self, reason=None, **kwargs):
        data = reason or self.default_reason
        if isinstance(data, Promise):
            # A lazy translation (e.g. a ValidationError message) is a string too.
            data = str(data)
        if data is None or isinstance(data, str):
            data = {"errors": {"detail": [{"message": data}],}}

        if settings.DEBUG:
            exc = sys.exc_info()
            if exc[0] is not None:
                data["meta"] = {"traceback": "".join(traceback.format_exception(*exc))}
        super().__init__(data, **kwargs)


class Http200(JSONResponse):
    """HTTP 200 OK"""

    pass


class Http201(JSONResponse):
    """HTTP 201 Created"""

    status_code = 201


class Http204(http.HttpResponse):
    """HTTP 204 No Content"""

    status_code = 204


class Http400(JSONErrorResponse):
    """HTTP 400 Bad Request"""

    status_code = 400


class Http401(JSONErrorResponse):
    """HTTP 401 Unauthorized"""

    status_code = 401


class Http403(JSONErrorResponse):
    """HTTP 403 Forbidden"""

    status_code = 403


class Http404(JSONErrorResponse):
    """HTTP 404 Not Found"""

    status_code = 404


class Http405(JSONResponse):
    """HTTP 405 Method Not Allowed"""

    status_code = 405

    def __init__(self, method, permitted_methods, *args, **kwargs):
        data = {
            "errors": {
                "detail": [{"message": _('Method "{0}" not allowed').format(method)}],
            }
        }
        super().__init__(data=data, *args, **kwargs)
        self["Allow"] = ", ".join(permitted_methods)


class Http409(JSONErrorResponse):
    """HTTP 409 Conflict"""

    status_code = 409


class Http500(JSONErrorResponse):
    """HTTP 500 Internal Server Error"""

    pass
