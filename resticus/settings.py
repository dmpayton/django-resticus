from django.conf import settings
from django.test.signals import setting_changed

from .compat import importlib

USER_SETTINGS = getattr(settings, "RESTICUS", None)

DEFAULTS = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "resticus.auth.SessionAuth",
        "resticus.auth.BasicHttpAuth",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("resticus.permissions.AllowAny",),
    "ERROR_HANDLER": None,
    "JSON_DECODER": "resticus.encoders.JSONDecoder",
    "JSON_ENCODER": "resticus.encoders.JSONEncoder",
    "LOGIN_REQUIRED": False,
    "DOCUMENTED": True,
    "DOCS_UI": "scalar",
    "TOKEN_MODEL": None,
    "DATA_PARSERS": {
        "application/json": "resticus.parsers.parse_json",
        "application/x-www-form-urlencoded": "resticus.parsers.parse_form_encoded",
        "multipart/form-data": "resticus.parsers.parse_multipart",
        "text/plain": "resticus.parsers.parse_plain_text",
    },

    # List of view class names that will stream the JSON response
    'STREAMING': [
        'resticus.mixins.ListModelMixin',
    ],

    # Pagination
    "PAGINATE": True,
    "PAGE_SIZE": 100,
    "PAGE_QUERY_PARAM": "page",
    "PAGE_SIZE_QUERY_PARAM": None,
    "MAX_PAGE_SIZE": 1000,
}

IMPORT_STRINGS = (
    "DEFAULT_AUTHENTICATION_CLASSES",
    "DEFAULT_PERMISSION_CLASSES",
    "JSON_DECODER",
    "JSON_ENCODER",
    "DATA_PARSERS",
    "ERROR_HANDLER",
)


def perform_import(val, setting_name):
    """
    If the given setting is a string import notation,
    then perform the necessary import or imports.
    """
    if val is None:
        return None
    elif isinstance(val, str):
        return import_from_string(val, setting_name)
    elif isinstance(val, (list, tuple)):
        return [import_from_string(item, setting_name) for item in val]
    elif isinstance(val, dict):
        return {
            key: import_from_string(item, setting_name) for key, item in val.items()
        }
    return val


def import_from_string(val, setting_name):
    """
    Attempt to import a class from a string representation.
    """
    try:
        # Nod to tastypie's use of importlib.
        parts = val.split(".")
        module_path, class_name = ".".join(parts[:-1]), parts[-1]
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except ImportError as e:
        msg = "Could not import '%s' for API setting '%s'. %s: %s." % (
            val,
            setting_name,
            e.__class__.__name__,
            e,
        )
        raise ImportError(msg)


class APISettings(object):
    """
    A settings object, that allows API settings to be accessed as properties.
    For example:
        from resticus.settings import api_settings
        print(api_settings.DEFAULT_AUTHENTICATION_CLASSES)
    Any setting with string import paths will be automatically resolved
    and return the class, rather than the string literal.
    """

    def __init__(self, user_settings=None, defaults=None, import_strings=None):
        self.user_settings = user_settings or {}
        self.defaults = defaults or DEFAULTS
        self.import_strings = import_strings or IMPORT_STRINGS

    def __getattr__(self, attr):
        if attr not in self.defaults.keys():
            raise AttributeError("Invalid API setting: '%s'" % attr)

        try:
            # Check if present in user settings
            val = self.user_settings[attr]
        except KeyError:
            # Fall back to defaults
            val = self.defaults[attr]

        # Coerce import strings into classes
        if val and attr in self.import_strings:
            val = perform_import(val, attr)

        # Cache the result
        setattr(self, attr, val)
        return val


api_settings = APISettings(USER_SETTINGS, DEFAULTS, IMPORT_STRINGS)


def reload_api_settings(*args, **kwargs):
    global api_settings
    setting, value = kwargs["setting"], kwargs["value"]
    if setting == "RESTICUS":
        api_settings = APISettings(value, DEFAULTS, IMPORT_STRINGS)


setting_changed.connect(reload_api_settings)
