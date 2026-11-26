import json

from django.test import SimpleTestCase, override_settings
from django.utils.translation import gettext_lazy

from resticus import http


def error_response_while_handling(reason):
    """Build an Http400 inside an except block, as dispatch does, so sys.exc_info() is set."""
    try:
        raise ValueError('original error')
    except ValueError:
        return http.Http400(reason)


class TestLazyErrorReasons(SimpleTestCase):
    """A lazy translation is a string: it gets the errors shape and never crashes."""

    @override_settings(DEBUG=True)
    def test_lazy_reason_in_debug(self):
        r = error_response_while_handling(gettext_lazy('Lazy reason'))
        body = json.loads(r.content)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(body['errors']['detail'][0]['message'], 'Lazy reason')
        self.assertIn('original error', body['meta']['traceback'])

    @override_settings(DEBUG=False)
    def test_lazy_reason_without_debug(self):
        body = json.loads(error_response_while_handling(gettext_lazy('Lazy reason')).content)
        self.assertEqual(body, {'errors': {'detail': [{'message': 'Lazy reason'}]}})
