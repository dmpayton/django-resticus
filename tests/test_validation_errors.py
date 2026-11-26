from django.test import TestCase, override_settings

from .client import ApiClient


class TestValidationErrorBody(TestCase):
    """A Django ValidationError reaching dispatch answers 400 in the errors shape."""
    client_class = ApiClient

    EXPECTED = {
        'single': {'detail': [{'message': "'x' is bad."}]},
        'list': {'detail': [{'message': 'one'}, {'message': 'two'}]},
        'dict': {'name': [{'message': 'Required.'}], 'detail': [{'message': 'Clash.'}]},
    }

    def check(self):
        for kind, errors in self.EXPECTED.items():
            r = self.client.get('validation_error', data={'kind': kind})
            self.assertEqual(r.status_code, 400, kind)
            self.assertEqual(r.json['errors'], errors, kind)

    @override_settings(DEBUG=False)
    def test_body(self):
        self.check()

    @override_settings(DEBUG=True)
    def test_body_in_debug(self):
        self.check()
