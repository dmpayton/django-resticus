import re

from django import forms as django_forms
from django.conf import settings
from django.contrib.admindocs.views import simplify_regex
from django.urls import URLPattern, URLResolver


FORM_FIELD_TYPE_MAP = {
    django_forms.CharField: {'type': 'string'},
    django_forms.SlugField: {'type': 'string'},
    django_forms.URLField: {'type': 'string'},
    django_forms.EmailField: {'type': 'string'},
    django_forms.RegexField: {'type': 'string'},
    django_forms.IntegerField: {'type': 'integer'},
    django_forms.FloatField: {'type': 'number'},
    django_forms.DecimalField: {'type': 'number'},
    django_forms.BooleanField: {'type': 'boolean'},
    django_forms.DateField: {'type': 'string', 'format': 'date'},
    django_forms.DateTimeField: {'type': 'string', 'format': 'date-time'},
}


def _form_field_to_schema(field):
    """Map a Django form field instance to an OpenAPI schema dict."""
    # ChoiceField first — it's a subclass of Field and needs special handling
    if isinstance(field, django_forms.ChoiceField):
        choices = [c[0] for c in field.choices if c[0] != '']
        schema = {'type': 'string'}
        if choices:
            schema['enum'] = [str(c) for c in choices]
        return schema

    for field_class, schema in FORM_FIELD_TYPE_MAP.items():
        if isinstance(field, field_class):
            return dict(schema)  # copy to avoid mutation

    return {'type': 'string'}  # safe fallback


def _get_form_fields(view_class):
    """Return list of (name, field) from view_class.form_class, or empty list."""
    form_class = getattr(view_class, 'form_class', None)
    if form_class is None:
        return []
    try:
        form = form_class()
        return list(form.fields.items())
    except Exception:
        return []


def _form_fields_to_query_params(fields):
    """Convert Django form fields to OpenAPI query parameter dicts."""
    return [
        {
            'name': name,
            'in': 'query',
            'required': field.required,
            'schema': _form_field_to_schema(field),
        }
        for name, field in fields
    ]


def _form_fields_to_request_body(fields):
    """Convert Django form fields to an OpenAPI requestBody dict."""
    properties = {name: _form_field_to_schema(field) for name, field in fields}
    required = [name for name, field in fields if field.required]
    schema = {'type': 'object', 'properties': properties}
    if required:
        schema['required'] = required
    return {
        'required': True,
        'content': {
            'application/json': {'schema': schema}
        }
    }


def _has_write_method(view_class):
    """Return True if the view has any write HTTP method."""
    return any(hasattr(view_class, m) for m in ('post', 'put', 'patch'))


def _get_filter_query_params(view_class):
    """Return OpenAPI query parameter dicts from a view's filter_class."""
    filter_class = getattr(view_class, 'filter_class', None)
    if filter_class is None:
        return []

    params = []
    for filter_name, filter_instance in filter_class.get_filters().items():
        schema = _form_field_to_schema(filter_instance.field)
        params.append({
            'name': filter_name,
            'in': 'query',
            'required': False,
            'schema': schema,
        })
    return params


def _import_urlconf(urlconf):
    """Accept a module, string dotted path, or object with urlpatterns."""
    if isinstance(urlconf, str):
        return __import__(urlconf, fromlist=[''])
    return urlconf


def _django_path_to_openapi(path_str):
    """Convert Django URL path to OpenAPI path, e.g. <monitor_id> → {monitor_id}."""
    return re.sub(r'<(?:[^:>]+:)?([^>]+)>', r'{\1}', path_str)


def _extract_path_params(openapi_path):
    """Return list of OpenAPI parameter dicts for each {param} in the path."""
    params = re.findall(r'\{(\w+)\}', openapi_path)
    return [
        {'name': p, 'in': 'path', 'required': True, 'schema': {'type': 'string'}}
        for p in params
    ]


class SchemaGenerator:
    def __init__(self, title=None, description=None, version=None,
                 prefix=None, urlconf=None):
        self.title = title or ''
        self.description = description
        self.version = version or ''
        self.prefix = prefix or ''

        if urlconf:
            self.urlconf = _import_urlconf(urlconf)
        else:
            self.urlconf = __import__(settings.ROOT_URLCONF, fromlist=[''])

    def get_schema(self, request=None):
        paths = self._collect_paths()

        schema = {
            'openapi': '3.1.0',
            'info': self._get_info(),
            'components': {
                'securitySchemes': {
                    'sessionAuth': {
                        'type': 'apiKey',
                        'in': 'cookie',
                        'name': 'sessionid',
                    }
                }
            },
            'paths': paths,
        }

        if self.prefix:
            schema['servers'] = [{'url': self.prefix}]

        return schema

    def _get_info(self):
        info = {'title': self.title, 'version': self.version}
        if self.description:
            info['description'] = self.description
        return info

    def _collect_paths(self):
        paths = {}
        self._walk_patterns(
            getattr(self.urlconf, 'urlpatterns', []),
            prefix='',
            paths=paths,
        )
        return paths

    def _walk_patterns(self, patterns, prefix, paths):
        for pattern in patterns:
            if isinstance(pattern, URLPattern):
                self._handle_url_pattern(pattern, prefix, paths)
            elif isinstance(pattern, URLResolver):
                sub_prefix = prefix + simplify_regex(str(pattern.pattern))
                self._walk_patterns(pattern.url_patterns, sub_prefix, paths)

    def _handle_url_pattern(self, pattern, prefix, paths):
        from resticus.views import Endpoint

        view_class = getattr(pattern.callback, 'view_class', None)
        if view_class is None:
            return
        if not issubclass(view_class, Endpoint):
            return
        if not getattr(view_class, 'documented', True):
            return

        raw_path = prefix + simplify_regex(str(pattern.pattern))
        openapi_path = _django_path_to_openapi(raw_path)
        # Normalise double slashes
        openapi_path = re.sub(r'//+', '/', openapi_path)
        if not openapi_path.startswith('/'):
            openapi_path = '/' + openapi_path

        path_item = self._build_path_item(view_class, openapi_path)
        if path_item:
            paths[openapi_path] = path_item

    def _build_path_item(self, view_class, openapi_path):
        """Build the OpenAPI path item object for a view class."""
        path_params = _extract_path_params(openapi_path)
        description = (view_class.__doc__ or '').strip()

        # Pre-compute form fields once for the view
        form_fields = _get_form_fields(view_class)
        has_write = _has_write_method(view_class)

        http_methods = ['get', 'post', 'put', 'patch', 'delete']
        operations = {}
        for method in http_methods:
            if hasattr(view_class, method):
                operations[method] = self._build_operation(
                    view_class, method, path_params, form_fields, has_write
                )

        if not operations:
            return None

        item = {}
        if description:
            item['description'] = description
        item.update(operations)
        return item

    def _build_operation(self, view_class, method, path_params,
                         form_fields=None, has_write=False):
        form_fields = form_fields or []
        method_func = getattr(view_class, method, None)
        summary = (getattr(method_func, '__doc__', None) or '').strip()

        # Auth: same logic as Endpoint.authenticate()
        method_login_required = getattr(
            method_func, 'login_required', view_class.login_required
        )

        parameters = list(path_params)

        if method == 'get':
            parameters += _get_filter_query_params(view_class)
            if form_fields and not has_write:
                parameters += _form_fields_to_query_params(form_fields)

        operation = {
            'parameters': parameters,
            'responses': {'200': {'description': 'OK'}},
        }

        if method in ('post', 'put', 'patch') and form_fields:
            operation['requestBody'] = _form_fields_to_request_body(form_fields)

        if method_login_required:
            operation['security'] = [{'sessionAuth': []}]

        if summary:
            operation['summary'] = summary

        return operation
