from io import BytesIO

from django.http.multipartparser import MultiPartParser, MultiPartParserError
from django.utils.translation import gettext as _

from .exceptions import ParseError
from .settings import api_settings


def parse_content_type(content_type):
    if ";" in content_type:
        content_type, params = content_type.split(";", 1)
        try:
            params = dict(param.split("=") for param in params.split())
        except Exception:
            params = {}
    else:
        params = {}
    return content_type, params


def parse_plain_text(request, **extra):
    return (request.body, None)


def parse_json(request, **extra):
    charset = extra.get("charset", "utf-8")
    if request.body:
        try:
            data = request.body.decode(charset)
            if data:
                return (api_settings.JSON_DECODER().decode(data), None)
            return (None, None)
        except Exception:
            raise ParseError()
    return None

def parse_form_encoded(request, **extra):
    return (request.POST, None)


def parse_multipart(request, **extra):
    if hasattr(request, "_body"):
        # Use already read data
        data = BytesIO(request._body)
    else:
        data = request

    try:
        return request.parse_file_upload(request.META, data)
    except MultiPartParserError as err:
        raise ParseError()
