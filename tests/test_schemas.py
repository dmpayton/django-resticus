import pytest
from django.test import TestCase, override_settings
from resticus.views import Endpoint
from resticus.settings import api_settings


class TestDocumentedAttribute(TestCase):
    def test_endpoint_documented_defaults_true(self):
        assert Endpoint.documented is True

    def test_subclass_can_override_documented_false(self):
        class MyView(Endpoint):
            documented = False
        assert MyView.documented is False

    def test_subclass_can_override_documented_true(self):
        class MyView(Endpoint):
            documented = True
        assert MyView.documented is True

    @override_settings(RESTICUS={'DOCUMENTED': False})
    def test_resticus_setting_controls_default(self):
        from resticus.settings import APISettings, DEFAULTS, IMPORT_STRINGS
        settings = APISettings({'DOCUMENTED': False}, DEFAULTS, IMPORT_STRINGS)
        assert settings.DOCUMENTED is False
