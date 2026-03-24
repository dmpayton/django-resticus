import re

from django.conf import settings
from django.contrib.admindocs.views import simplify_regex
from django.urls import URLPattern, URLResolver


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

        http_methods = ['get', 'post', 'put', 'patch', 'delete']
        operations = {}
        for method in http_methods:
            if hasattr(view_class, method):
                operations[method] = self._build_operation(
                    view_class, method, path_params
                )

        if not operations:
            return None

        item = {}
        if description:
            item['description'] = description
        item.update(operations)
        return item

    def _build_operation(self, view_class, method, path_params):
        """Build one operation dict. Introspection details added in later tasks."""
        method_func = getattr(view_class, method, None)
        summary = (getattr(method_func, '__doc__', None) or '').strip()

        operation = {
            'parameters': list(path_params),
            'responses': {'200': {'description': 'OK'}},
        }
        if summary:
            operation['summary'] = summary
        return operation
