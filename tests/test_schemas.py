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

    @override_settings(RESTICUS={'DOCUMENTED': False})
    def test_resticus_setting_controls_default(self):
        # override_settings triggers the setting_changed signal, which reloads
        # api_settings via reload_api_settings. Verify the live singleton reflects it.
        from resticus.settings import api_settings as live_settings
        assert live_settings.DOCUMENTED is False
