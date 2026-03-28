import inspect
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
    if isinstance(field, django_forms.ChoiceField):
        choices = [c[0] for c in field.choices if c[0] != '']
        schema = {'type': 'string'}
        if choices:
            schema['enum'] = [str(c) for c in choices]
        return schema

    for field_class, schema in FORM_FIELD_TYPE_MAP.items():
        if isinstance(field, field_class):
            return dict(schema)

    return {'type': 'string'}


def _flatten_choices(choices):
    """Flatten potentially grouped Django choices to a flat list of values."""
    values = []
    for value, label in choices:
        if isinstance(label, (list, tuple)):
            values.extend(v for v, _ in label)
        else:
            values.append(value)
    return values


def _model_field_to_schema(model_field):
    """Map a Django model field instance to an OpenAPI schema dict.

    Handles type, format, enum (from choices), and nullability.
    """
    from django.db import models

    # GIS fields (requires django.contrib.gis)
    try:
        from django.contrib.gis.db.models import GeometryField
        if isinstance(model_field, GeometryField):
            schema = {'type': 'object'}
            if getattr(model_field, 'null', False):
                schema['type'] = ['object', 'null']
            return schema
    except ImportError:
        pass

    # Relational fields
    if isinstance(model_field, models.ForeignKey):
        try:
            return _model_field_to_schema(model_field.related_model._meta.pk)
        except Exception:
            return {'type': 'string'}
    if isinstance(model_field, models.ManyToManyField):
        try:
            item_schema = _model_field_to_schema(model_field.related_model._meta.pk)
        except Exception:
            item_schema = {'type': 'string'}
        return {'type': 'array', 'items': item_schema}

    # Ordered most-specific first (DateTimeField is a subclass of DateField)
    if isinstance(model_field, models.DateTimeField):
        base = {'type': 'string', 'format': 'date-time'}
    elif isinstance(model_field, models.DateField):
        base = {'type': 'string', 'format': 'date'}
    elif isinstance(model_field, models.TimeField):
        base = {'type': 'string', 'format': 'time'}
    elif isinstance(model_field, models.UUIDField):
        base = {'type': 'string', 'format': 'uuid'}
    elif isinstance(model_field, (
        models.AutoField, models.SmallAutoField, models.BigAutoField,
        models.IntegerField, models.SmallIntegerField, models.BigIntegerField,
        models.PositiveIntegerField, models.PositiveSmallIntegerField,
        models.PositiveBigIntegerField,
    )):
        base = {'type': 'integer'}
    elif isinstance(model_field, (models.FloatField, models.DecimalField)):
        base = {'type': 'number'}
    elif isinstance(model_field, models.BooleanField):
        base = {'type': 'boolean'}
    elif isinstance(model_field, models.JSONField):
        return {}  # any type — nullable doesn't narrow this further
    elif isinstance(model_field, models.FileField):
        base = {'type': 'string'}
    else:
        base = {'type': 'string'}  # CharField, TextField, SlugField, etc.

    schema = dict(base)

    # Add enum from field choices
    choices = getattr(model_field, 'choices', None)
    if choices:
        values = _flatten_choices(choices)
        if values:
            schema['enum'] = [str(v) for v in values]

    # maxLength for bounded string fields (CharField, SlugField, etc.)
    max_length = getattr(model_field, 'max_length', None)
    if max_length and schema.get('type') == 'string':
        schema['maxLength'] = max_length

    # description from help_text
    help_text = str(getattr(model_field, 'help_text', '') or '')
    if help_text:
        schema['description'] = help_text

    # Nullability — OpenAPI 3.1 allows type arrays
    if getattr(model_field, 'null', False):
        base_type = schema.get('type')
        if base_type and isinstance(base_type, str):
            schema['type'] = [base_type, 'null']

    return schema


def _serializer_to_schema(serializer_class, model=None):
    """Convert a resticus Serializer class's declared fields to an OpenAPI properties dict.

    Handles string fields (looked up against the model), tuple (key, Serializer) for
    nested objects, and tuple (key, callable) for computed fields (emitted as any-type).
    The fixup method and dynamically added fields cannot be statically introspected.
    """
    from resticus.serializers import Serializer

    fields = getattr(serializer_class, 'fields', None)
    include = getattr(serializer_class, 'include', None) or []
    exclude = set(getattr(serializer_class, 'exclude', None) or [])

    if fields is None:
        if model is None:
            return {}
        fields = [f.name for f in model._meta.local_fields]

    properties = {}
    for field in list(fields) + list(include):
        if isinstance(field, str):
            if field in exclude:
                continue
            if model is not None:
                try:
                    model_field = model._meta.get_field(field)
                    properties[field] = _model_field_to_schema(model_field)
                    continue
                except Exception:
                    pass
            properties[field] = {}

        elif isinstance(field, tuple) and len(field) == 2:
            key, value = field
            if key in exclude:
                continue
            if inspect.isclass(value) and issubclass(value, Serializer):
                nested = _serializer_to_schema(value)
                properties[key] = (
                    {'type': 'object', 'properties': nested} if nested
                    else {'type': 'object'}
                )
            else:
                properties[key] = {}

    return properties


_ERROR_RESPONSE_SCHEMA = {
    'type': 'object',
    'required': ['errors'],
    'properties': {
        'errors': {
            'type': 'object',
            'additionalProperties': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {'message': {'type': 'string'}},
                    'required': ['message'],
                },
            },
        },
    },
}


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
        'content': {'application/json': {'schema': schema}},
    }


def _has_write_method(view_class):
    """Return True if the view has any write HTTP method."""
    return any(hasattr(view_class, m) for m in ('post', 'put', 'patch'))


def _get_uses_form(view_class):
    """Return True if the view's GET handler uses form_class for query params."""
    for cls in view_class.__mro__:
        if 'get' in cls.__dict__:
            return 'form_class' in cls.__dict__ or 'process_form' in cls.__dict__
    return False


def _get_pagination_query_params(view_class):
    """Return OpenAPI query parameter dicts for pagination if the view paginates."""
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
    """Return OpenAPI path parameter dicts with types from Django converters."""
    params = []
    for match in re.finditer(r'<(?:([^:>]+):)?([^>]+)>', raw_django_path):
        converter, name = match.group(1), match.group(2)
        schema = dict(DJANGO_PATH_CONVERTER_MAP.get(converter or 'str', {'type': 'string'}))
        params.append({'name': name, 'in': 'path', 'required': True, 'schema': schema})
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


class SchemaGenerator:
    def __init__(self, title=None, description=None, version=None,
                 prefix=None, urlconf=None):
        self.title = title or ''
        self.description = description
        self.version = version or ''
        self.prefix = prefix or ''
        self._component_schemas = {}

        if urlconf:
            self.urlconf = _import_urlconf(urlconf)
        else:
            self.urlconf = __import__(settings.ROOT_URLCONF, fromlist=[''])

    def get_schema(self, request=None):
        self._security_schemes = self._get_security_schemes()
        self._component_schemas['ErrorResponse'] = _ERROR_RESPONSE_SCHEMA
        paths = self._collect_paths()

        components = {
            'securitySchemes': self._security_schemes,
            'schemas': self._component_schemas,
        }

        schema = {
            'openapi': '3.1.0',
            'info': self._get_info(),
            'components': components,
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

    def _get_security_schemes(self):
        """Build the securitySchemes dict from configured auth classes."""
        schemes = {
            'sessionAuth': {
                'type': 'apiKey',
                'in': 'cookie',
                'name': 'sessionid',
            }
        }
        try:
            from resticus.auth import TokenAuth
            from resticus.settings import api_settings
            auth_classes = api_settings.DEFAULT_AUTHENTICATION_CLASSES
            if any(issubclass(cls, TokenAuth) for cls in auth_classes):
                schemes['tokenAuth'] = {
                    'type': 'apiKey',
                    'in': 'header',
                    'name': 'Authorization',
                    'description': 'Token-based authentication. Pass as `Authorization: Token <key>`.',
                }
        except Exception:
            pass
        return schemes

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
        openapi_path = re.sub(r'//+', '/', openapi_path)
        if not openapi_path.startswith('/'):
            openapi_path = '/' + openapi_path

        path_item = self._build_path_item(view_class, raw_path, openapi_path, pattern.name)
        if path_item:
            paths[openapi_path] = path_item

    def _build_path_item(self, view_class, raw_path, openapi_path, url_name=None):
        path_params = _extract_path_params(raw_path)
        description = (view_class.__doc__ or '').strip()
        form_fields = _get_form_fields(view_class)
        get_uses_form = _get_uses_form(view_class)
        tags = (
            list(view_class.tags) if getattr(view_class, 'tags', None)
            else _derive_tags_from_path(openapi_path)
        )

        operations = {}
        for method in ['get', 'post', 'put', 'patch', 'delete']:
            if hasattr(view_class, method):
                operations[method] = self._build_operation(
                    view_class, method, path_params, form_fields, get_uses_form, tags,
                    description=description, url_name=url_name,
                )

        if not operations:
            return None

        item = {}
        item.update(operations)
        return item

    def _register_component_schema(self, serializer_class, model=None):
        """Register a serializer's item schema in components/schemas, return its name."""
        name = serializer_class.__name__
        if name not in self._component_schemas:
            properties = _serializer_to_schema(serializer_class, model)
            if properties:
                self._component_schemas[name] = {
                    'type': 'object',
                    'required': list(properties.keys()),
                    'properties': properties,
                }
        return name

    def _build_response_content(self, view_class):
        """Build the 200 response content schema for list/detail endpoints, or None."""
        from resticus.serializers import Serializer
        from resticus.mixins import ListModelMixin, DetailModelMixin

        is_list = issubclass(view_class, ListModelMixin)
        is_detail = issubclass(view_class, DetailModelMixin)
        if not (is_list or is_detail):
            return None

        serializer_class = getattr(view_class, 'serializer_class', None)
        if serializer_class is None:
            return None
        if not (inspect.isclass(serializer_class) and issubclass(serializer_class, Serializer)):
            return None

        model = getattr(view_class, 'model', None)
        schema_name = self._register_component_schema(serializer_class, model)
        if schema_name not in self._component_schemas:
            return None

        item_ref = {'$ref': f'#/components/schemas/{schema_name}'}
        response_properties = {}

        if is_list:
            response_properties['data'] = {'type': 'array', 'items': item_ref}
            if getattr(view_class, 'paginate', False):
                response_properties['page'] = {'type': 'integer'}
                response_properties['count'] = {'type': 'integer'}
                response_properties['pages'] = {'type': 'integer'}
                response_properties['has_next_page'] = {'type': 'boolean'}
                response_properties['has_previous_page'] = {'type': 'boolean'}
        else:
            response_properties['data'] = item_ref

        return {
            'application/json': {
                'schema': {'type': 'object', 'properties': response_properties}
            }
        }

    def _build_responses(self, method, view_class, method_login_required,
                         form_fields, get_uses_form):
        from resticus.mixins import DetailModelMixin, CreateModelMixin, DeleteModelMixin

        # Base success response
        if method == 'delete' and issubclass(view_class, DeleteModelMixin):
            responses = {'204': {'description': 'No content'}}
        elif method in ('post', 'put', 'patch') and issubclass(view_class, CreateModelMixin):
            responses = {'201': {'description': 'Created'}}
        else:
            ok_response = {'description': 'OK'}
            if method == 'get':
                content = self._build_response_content(view_class)
                if content:
                    ok_response['content'] = content
            responses = {'200': ok_response}

        error_content = {'application/json': {'schema': {'$ref': '#/components/schemas/ErrorResponse'}}}

        # 400 for endpoints that validate form/query input
        if (method in ('post', 'put', 'patch') and form_fields) or \
           (method == 'get' and form_fields and get_uses_form):
            responses['400'] = {'description': 'Bad request', 'content': error_content}

        # 401/403 for auth-required endpoints
        if method_login_required:
            responses['401'] = {'description': 'Authentication required', 'content': error_content}
            responses['403'] = {'description': 'Permission denied', 'content': error_content}

        # 404 for detail endpoints
        if issubclass(view_class, DetailModelMixin):
            responses['404'] = {'description': 'Not found', 'content': error_content}

        return responses

    def _build_operation(self, view_class, method, path_params,
                         form_fields=None, get_uses_form=False, tags=None,
                         description=None, url_name=None):
        form_fields = form_fields or []
        method_func = getattr(view_class, method, None)

        if method in view_class.__dict__:
            summary = (getattr(method_func, '__doc__', None) or '').strip()
        else:
            summary = ''

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
            'responses': self._build_responses(
                method, view_class, method_login_required, form_fields, get_uses_form
            ),
        }

        if method in ('post', 'put', 'patch') and form_fields:
            operation['requestBody'] = _form_fields_to_request_body(form_fields)

        if method_login_required:
            operation['security'] = [{name: []} for name in self._security_schemes]

        if tags:
            operation['tags'] = tags

        if description:
            operation['description'] = description

        if summary:
            operation['summary'] = summary

        if getattr(view_class, 'deprecated', False):
            operation['deprecated'] = True

        return operation
