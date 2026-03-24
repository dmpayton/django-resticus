import pytest
from django.test import TestCase, override_settings
from django.urls import path
from resticus.views import Endpoint
from resticus.settings import api_settings
from resticus import generics
from resticus.schemas import SchemaGenerator


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
