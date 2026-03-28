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

# Maps Django URL path converter names to OpenAPI schema dicts.
DJANGO_PATH_CONVERTER_MAP = {
    'int': {'type': 'integer'},
    'uuid': {'type': 'string', 'format': 'uuid'},
    'slug': {'type': 'string'},
    'str': {'type': 'string'},
    'path': {'type': 'string'},
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


def _get_uses_form(view_class):
    """Return True if the view's GET handler uses form_class for query params.

    Walks the MRO to find the class that defines `get`. If that class also
    owns `form_class` or `process_form`, the form fields should be exposed as
    GET query parameters. This distinguishes export-style endpoints (where GET
    accepts form fields as query params) from list-create endpoints (where the
    form is only used for the POST body).
    """
    for cls in view_class.__mro__:
        if 'get' in cls.__dict__:
            return 'form_class' in cls.__dict__ or 'process_form' in cls.__dict__
    return False


def _get_pagination_query_params(view_class):
    """Return OpenAPI query parameter dicts for pagination if the view paginates.

    Only list-style endpoints (those using ListModelMixin) actually paginate;
    detail endpoints inherit the paginate attribute but never call paginate_queryset.
    """
    from resticus.mixins import ListModelMixin
    if not issubclass(view_class, ListModelMixin):
        return []
    if not getattr(view_class, 'paginate', False):
        return []
    params = [{
        'name': getattr(view_class, 'page_query_param', 'page'),
        'in': 'query',
        'required': False,
        'schema': {'type': 'integer'},
    }]
    page_size_param = getattr(view_class, 'page_size_query_param', None)
    if page_size_param:
        params.append({
            'name': page_size_param,
            'in': 'query',
            'required': False,
            'schema': {'type': 'integer'},
        })
    return params


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


def _extract_path_params(raw_django_path):
    """Return OpenAPI path parameter dicts parsed from a Django URL pattern.

    Preserves type information from Django path converters:
    <int:pk> → type: integer, <uuid:id> → type: string/format: uuid, etc.
    """
    params = []
    for match in re.finditer(r'<(?:([^:>]+):)?([^>]+)>', raw_django_path):
        converter, name = match.group(1), match.group(2)
        schema = dict(DJANGO_PATH_CONVERTER_MAP.get(converter or 'str', {'type': 'string'}))
        params.append({
            'name': name,
            'in': 'path',
            'required': True,
            'schema': schema,
        })
    return params


def _derive_tags_from_path(openapi_path):
    """Derive a tag from the first non-empty path segment."""
    parts = openapi_path.strip('/').split('/')
    first = parts[0] if parts else ''
    return [first] if first else []


def _make_operation_id(url_name, method):
    """Build a unique operationId from the URL name and HTTP method."""
    sanitized = re.sub(r'[^a-zA-Z0-9]+', '_', url_name or '').strip('_')
    return f'{sanitized}_{method}'


def _build_responses(method, view_class, method_login_required, form_fields, get_uses_form):
    """Build the OpenAPI responses object for an operation."""
    from resticus.mixins import DetailModelMixin

    responses = {'200': {'description': 'OK'}}

    # 400 for endpoints that validate form/query input
    if (method in ('post', 'put', 'patch') and form_fields) or \
       (method == 'get' and form_fields and get_uses_form):
        responses['400'] = {'description': 'Bad request'}

    # 401/403 for auth-required endpoints (resticus returns 401 with WWW-Authenticate
    # header present, 403 otherwise — depends on the configured auth backends)
    if method_login_required:
        responses['401'] = {'description': 'Authentication required'}
        responses['403'] = {'description': 'Permission denied'}

    # 404 for detail endpoints
    if issubclass(view_class, DetailModelMixin):
        responses['404'] = {'description': 'Not found'}

    return responses


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

        path_item = self._build_path_item(view_class, raw_path, openapi_path, pattern.name)
        if path_item:
            paths[openapi_path] = path_item

    def _build_path_item(self, view_class, raw_path, openapi_path, url_name=None):
        """Build the OpenAPI path item object for a view class."""
        path_params = _extract_path_params(raw_path)
        description = (view_class.__doc__ or '').strip()

        form_fields = _get_form_fields(view_class)
        get_uses_form = _get_uses_form(view_class)
        tags = list(view_class.tags) if getattr(view_class, 'tags', None) else _derive_tags_from_path(openapi_path)

        http_methods = ['get', 'post', 'put', 'patch', 'delete']
        operations = {}
        for method in http_methods:
            if hasattr(view_class, method):
                operations[method] = self._build_operation(
                    view_class, method, path_params, form_fields, get_uses_form, tags,
                    description=description,
                    url_name=url_name,
                )

        if not operations:
            return None

        item = {}
        item.update(operations)
        return item

    def _build_operation(self, view_class, method, path_params,
                         form_fields=None, get_uses_form=False, tags=None,
                         description=None, url_name=None):
        form_fields = form_fields or []
        method_func = getattr(view_class, method, None)

        # Only use the method docstring as summary if the method is defined
        # directly on this class, not inherited from a base class.
        if method in view_class.__dict__:
            summary = (getattr(method_func, '__doc__', None) or '').strip()
        else:
            summary = ''

        # Auth: same logic as Endpoint.authenticate()
        method_login_required = getattr(
            method_func, 'login_required', view_class.login_required
        )

        parameters = list(path_params)

        if method == 'get':
            parameters += _get_pagination_query_params(view_class)
            parameters += _get_filter_query_params(view_class)
            if form_fields and get_uses_form:
                parameters += _form_fields_to_query_params(form_fields)

        operation = {
            'operationId': _make_operation_id(url_name, method),
            'parameters': parameters,
            'responses': _build_responses(method, view_class, method_login_required, form_fields, get_uses_form),
        }

        if method in ('post', 'put', 'patch') and form_fields:
            operation['requestBody'] = _form_fields_to_request_body(form_fields)

        if method_login_required:
            operation['security'] = [{'sessionAuth': []}]

        if tags:
            operation['tags'] = tags

        if description:
            operation['description'] = description

        if summary:
            operation['summary'] = summary

        if getattr(view_class, 'deprecated', False):
            operation['deprecated'] = True

        return operation
