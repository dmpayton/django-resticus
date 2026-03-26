import pytest
from django.test import TestCase, override_settings
from django.urls import path
from resticus.views import Endpoint
from resticus.settings import api_settings
from resticus import generics
from resticus.schemas import SchemaGenerator
from tests.testapp.filters import BookFilter


class TestDocumentedAttribute(TestCase):
    def test_endpoint_documented_defaults_true(self):
        assert Endpoint.documented is True

    def test_subclass_can_override_documented_false(self):
        class MyView(Endpoint):
            documented = False
        assert MyView.documented is False

    @override_settings(RESTICUS={'DOCUMENTED': False})
    def test_resticus_setting_controls_default(self):
        # override_settings triggers the setting_changed signal, which reloads
        # api_settings via reload_api_settings. Verify the live singleton reflects it.
        from resticus.settings import api_settings as live_settings
        assert live_settings.DOCUMENTED is False


class DocumentedView(generics.ListEndpoint):
    """A documented endpoint."""
    model = None
    documented = True

    def get_queryset(self):
        return []


class HiddenView(Endpoint):
    documented = False

    def get(self, request):
        return {}


class DetailView(generics.DetailEndpoint):
    model = None

    def get_object(self):
        return None


test_urlconf_patterns = [
    path('items/', DocumentedView.as_view(), name='item-list'),
    path('items/<int:pk>/', DetailView.as_view(), name='item-detail'),
    path('hidden/', HiddenView.as_view(), name='hidden'),
]


class FakeURLConf:
    urlpatterns = test_urlconf_patterns


class TestSchemaGeneratorTraversal(TestCase):
    def setUp(self):
        self.generator = SchemaGenerator(
            title='Test API',
            version='1.0',
            urlconf=FakeURLConf,
        )

    def test_documented_endpoint_appears_in_paths(self):
        schema = self.generator.get_schema()
        assert '/items/' in schema['paths']

    def test_undocumented_endpoint_excluded_from_paths(self):
        schema = self.generator.get_schema()
        assert '/hidden/' not in schema['paths']

    def test_schema_has_openapi_version(self):
        schema = self.generator.get_schema()
        assert schema['openapi'] == '3.1.0'

    def test_schema_has_info_block(self):
        schema = self.generator.get_schema()
        assert schema['info']['title'] == 'Test API'
        assert schema['info']['version'] == '1.0'

    def test_schema_has_security_schemes(self):
        schema = self.generator.get_schema()
        assert 'sessionAuth' in schema['components']['securitySchemes']

    def test_path_parameters_converted_to_openapi_style(self):
        schema = self.generator.get_schema()
        assert '/items/{pk}/' in schema['paths']
        params = schema['paths']['/items/{pk}/']['get']['parameters']
        assert any(p['name'] == 'pk' and p['in'] == 'path' for p in params)


class FilteredView(generics.ListEndpoint):
    model = None
    filter_class = BookFilter

    def get_queryset(self):
        return []


filtered_urlconf_patterns = [
    path('books/', FilteredView.as_view(), name='book-list'),
]


class FakeFilteredURLConf:
    urlpatterns = filtered_urlconf_patterns


class TestFilterIntrospection(TestCase):
    def setUp(self):
        self.generator = SchemaGenerator(urlconf=FakeFilteredURLConf)

    def test_filter_fields_appear_as_query_params(self):
        schema = self.generator.get_schema()
        params = schema['paths']['/books/']['get']['parameters']
        param_names = [p['name'] for p in params]
        assert 'price' in param_names or any('price' in n for n in param_names)

    def test_filter_params_have_in_query(self):
        schema = self.generator.get_schema()
        params = schema['paths']['/books/']['get']['parameters']
        query_params = [p for p in params if p['in'] == 'query']
        assert len(query_params) > 0

    def test_filter_lookup_suffixes_are_separate_params(self):
        schema = self.generator.get_schema()
        params = schema['paths']['/books/']['get']['parameters']
        param_names = [p['name'] for p in params]
        # BookFilter has price__exact, price__lt, price__lte, price__gt, price__gte
        # Check that at least two price-related params exist
        price_params = [n for n in param_names if 'price' in n]
        assert len(price_params) >= 2


from tests.testapp.forms import AuthorForm
from tests.testapp.views import AuthorList   # ListCreateEndpoint with form_class=AuthorForm


class GetOnlyFormView(Endpoint):
    """GET-only endpoint with a form_class."""
    form_class = AuthorForm

    def get(self, request):
        return {}


form_urlconf_patterns = [
    path('authors/', AuthorList.as_view(), name='author-list'),
    path('search/', GetOnlyFormView.as_view(), name='author-search'),
]


class FakeFormURLConf:
    urlpatterns = form_urlconf_patterns


class TestFormIntrospection(TestCase):
    def setUp(self):
        self.generator = SchemaGenerator(urlconf=FakeFormURLConf)
        self.schema = self.generator.get_schema()

    def test_post_endpoint_has_request_body(self):
        # AuthorList is a ListCreateEndpoint (has post)
        assert 'requestBody' in self.schema['paths']['/authors/']['post']

    def test_request_body_contains_form_fields(self):
        body = self.schema['paths']['/authors/']['post']['requestBody']
        props = body['content']['application/json']['schema']['properties']
        assert 'name' in props

    def test_get_only_form_fields_become_query_params(self):
        params = self.schema['paths']['/search/']['get']['parameters']
        param_names = [p['name'] for p in params]
        assert 'name' in param_names

    def test_get_only_form_params_have_in_query(self):
        params = self.schema['paths']['/search/']['get']['parameters']
        for p in params:
            if p['name'] == 'name':
                assert p['in'] == 'query'


class AuthRequiredView(Endpoint):
    login_required = True

    def get(self, request):
        return {}


class PerMethodAuthView(Endpoint):
    login_required = False

    def get(self, request):
        return {}

    def post(self, request):
        return {}


# Set login_required only on get
PerMethodAuthView.get.login_required = True


auth_urlconf_patterns = [
    path('secure/', AuthRequiredView.as_view(), name='secure'),
    path('mixed/', PerMethodAuthView.as_view(), name='mixed'),
]


class FakeAuthURLConf:
    urlpatterns = auth_urlconf_patterns


class TestAuthIntrospection(TestCase):
    def setUp(self):
        self.generator = SchemaGenerator(urlconf=FakeAuthURLConf)
        self.schema = self.generator.get_schema()

    def test_class_level_login_required_adds_security(self):
        get_op = self.schema['paths']['/secure/']['get']
        assert 'security' in get_op
        assert {'sessionAuth': []} in get_op['security']

    def test_unauthenticated_endpoint_has_no_security(self):
        post_op = self.schema['paths']['/mixed/']['post']
        assert 'security' not in post_op or post_op.get('security') == []

    def test_per_method_login_required_adds_security_to_that_method(self):
        get_op = self.schema['paths']['/mixed/']['get']
        assert 'security' in get_op
        assert {'sessionAuth': []} in get_op['security']


from django.test import RequestFactory
from resticus.views import OpenAPISchemaView


class TestOpenAPISchemaView(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_returns_json_response(self):
        view = OpenAPISchemaView.as_view(
            title='Test',
            version='1.0',
            urlconf=FakeURLConf,
        )
        request = self.factory.get('/openapi.json')
        response = view(request)
        assert response.status_code == 200
        assert 'application/json' in response['Content-Type']

    def test_prefix_derived_from_request_path(self):
        import json
        view = OpenAPISchemaView.as_view(
            title='Test',
            version='1.0',
            urlconf=FakeURLConf,
        )
        request = self.factory.get('/api/2.0/openapi.json')
        response = view(request)
        schema = json.loads(response.content)
        assert schema['servers'] == [{'url': '/api/2.0/'}]

    def test_schema_view_is_not_documented(self):
        assert OpenAPISchemaView.documented is False


from resticus.views import DocsView


class TestDocsView(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _get(self, ui='scalar'):
        view = DocsView.as_view(
            ui=ui,
            schema_url='/api/2.0/openapi.json',
            title='Test API',
        )
        request = self.factory.get('/docs/')
        return view(request)

    def test_scalar_returns_html(self):
        response = self._get('scalar')
        assert response.status_code == 200
        assert 'text/html' in response['Content-Type']
        assert b'@scalar/api-reference' in response.content

    def test_swagger_returns_html(self):
        response = self._get('swagger')
        assert b'swagger-ui-bundle' in response.content

    def test_redoc_returns_html(self):
        response = self._get('redoc')
        assert b'redoc.standalone' in response.content

    def test_elements_returns_html(self):
        response = self._get('elements')
        assert b'stoplight/elements' in response.content

    def test_schema_url_is_embedded(self):
        response = self._get('scalar')
        assert b'/api/2.0/openapi.json' in response.content

    def test_title_is_embedded(self):
        response = self._get('scalar')
        assert b'Test API' in response.content

    def test_unknown_ui_raises(self):
        with pytest.raises((ValueError, KeyError)):
            self._get('nonexistent')

    def test_docs_view_is_not_documented(self):
        assert DocsView.documented is False
