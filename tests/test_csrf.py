import base64
import json

from django.contrib.auth.signals import user_login_failed
from django.test import RequestFactory, TestCase
from django.test.client import encode_multipart

from resticus.auth import TokenAuth
from resticus.parsers import parse_multipart
from resticus.compat import get_user_model
from .client import ApiClient


CSRF = 'a' * 32


def basic(username, password):
    credentials = '{0}:{1}'.format(username, password).encode('ascii')
    return 'Basic {0}'.format(base64.b64encode(credentials).decode('ascii'))


class TestSessionCsrf(TestCase):
    """Session-authenticated unsafe requests must pass Django's CSRF check."""

    def setUp(self):
        User = get_user_model()
        Token = TokenAuth.get_token_model()
        self.user = User.objects.create_user(username='foo', password='bar')
        self.token = Token.objects.create(user=self.user)
        self.other = User.objects.create_user(username='baz', password='qux')
        self.other_token = Token.objects.create(user=self.other)
        self.client = ApiClient(enforce_csrf_checks=True)

    def sign_in(self):
        self.client.login(username='foo', password='bar')

    def with_csrf(self, header=CSRF):
        self.client.cookies['csrftoken'] = CSRF
        return {'HTTP_X_CSRFTOKEN': header}

    def assertCsrfRejected(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertIn('CSRF Failed', response.content.decode('utf-8'))

    def assertUsername(self, response, username):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['username'], username)

    def test_session_post_without_csrf_rejected(self):
        self.sign_in()
        self.assertCsrfRejected(self.client.post('csrf_probe'))

    def test_session_put_patch_delete_without_csrf_rejected(self):
        self.sign_in()
        self.assertCsrfRejected(self.client.put('csrf_probe'))
        self.assertCsrfRejected(self.client.patch('csrf_probe'))
        self.assertCsrfRejected(self.client.delete('csrf_probe'))

    def test_session_post_with_csrf_accepted(self):
        self.sign_in()
        r = self.client.post('csrf_probe', extra=self.with_csrf())
        self.assertUsername(r, 'foo')

    def test_session_multipart_post_with_csrf_keeps_body(self):
        self.sign_in()
        r = self.client.post('csrf_probe', data={'name': 'x'}, extra=self.with_csrf())
        self.assertUsername(r, 'foo')
        self.assertEqual(r.json['name'], 'x')

    def test_session_form_post_with_csrf_keeps_body(self):
        self.sign_in()
        r = self.client.post('csrf_probe', data='name=x',
            content_type='application/x-www-form-urlencoded', extra=self.with_csrf())
        self.assertUsername(r, 'foo')
        self.assertEqual(r.json['name'], 'x')

    def test_session_json_post_with_csrf_keeps_body(self):
        self.sign_in()
        r = self.client.post('csrf_probe', data=json.dumps({'name': 'x'}),
            content_type='application/json', extra=self.with_csrf())
        self.assertUsername(r, 'foo')
        self.assertEqual(r.json['name'], 'x')

    def test_session_malformed_multipart_with_csrf_is_bad_request(self):
        self.sign_in()
        r = self.client.post('csrf_probe', data='garbage',
            content_type='multipart/form-data; boundary=', extra=self.with_csrf())
        self.assertEqual(r.status_code, 400)

    def test_session_post_with_mismatched_csrf_rejected(self):
        self.sign_in()
        r = self.client.post('csrf_probe', extra=self.with_csrf(header='b' * 32))
        self.assertCsrfRejected(r)

    def test_token_only_post_accepted(self):
        r = self.client.post('csrf_probe', extra={
            'HTTP_AUTHORIZATION': 'Token {0}'.format(self.token.key),
        })
        self.assertUsername(r, 'foo')

    def test_session_get_unaffected(self):
        self.sign_in()
        self.assertUsername(self.client.get('csrf_probe'), 'foo')

    def test_session_and_valid_token_skips_csrf(self):
        self.sign_in()
        r = self.client.post('csrf_probe', extra={
            'HTTP_AUTHORIZATION': 'Token {0}'.format(self.other_token.key),
        })
        self.assertUsername(r, 'foo')

    def test_session_and_invalid_token_checks_csrf(self):
        self.sign_in()
        r = self.client.post('csrf_probe', extra={'HTTP_AUTHORIZATION': 'Token not-a-key'})
        self.assertCsrfRejected(r)

    def test_session_and_malformed_token_checks_csrf(self):
        self.sign_in()
        r = self.client.post('csrf_probe', extra={'HTTP_AUTHORIZATION': 'Token'})
        self.assertCsrfRejected(r)

    def test_token_only_undecodable_key_rejected(self):
        r = self.client.post('csrf_probe', extra={'HTTP_AUTHORIZATION': 'Token \xff\xfe'})
        self.assertEqual(r.status_code, 401)

    def test_session_and_undecodable_token_checks_csrf(self):
        self.sign_in()
        r = self.client.post('csrf_probe', extra=dict(
            self.with_csrf(), HTTP_AUTHORIZATION='Token \xff\xfe'))
        self.assertUsername(r, 'foo')

    def test_session_and_valid_basic_skips_csrf(self):
        self.sign_in()
        r = self.client.post('csrf_probe', extra={'HTTP_AUTHORIZATION': basic('baz', 'qux')})
        self.assertUsername(r, 'foo')

    def test_session_get_skips_credential_lookup(self):
        failed = []

        def record(sender, **kwargs):
            failed.append(kwargs)

        user_login_failed.connect(record)
        try:
            self.sign_in()
            r = self.client.get('csrf_probe', extra={'HTTP_AUTHORIZATION': basic('baz', 'wrong')})
        finally:
            user_login_failed.disconnect(record)
        self.assertUsername(r, 'foo')
        self.assertEqual(failed, [])

    def test_anonymous_post_unaffected(self):
        r = self.client.post('echo_view')
        self.assertEqual(r.status_code, 200)

    def test_session_post_to_token_login_needs_csrf(self):
        self.sign_in()
        r = self.client.post('token_auth', data={'username': 'foo', 'password': 'bar'})
        self.assertCsrfRejected(r)


class TestParseMultipart(TestCase):
    def test_put_body_parsed_even_if_post_was_read(self):
        """Django leaves request.POST empty for non-POST methods; don't reuse it."""
        request = RequestFactory().put('/', data=encode_multipart('BoUnDaRy', {'name': 'x'}),
            content_type='multipart/form-data; boundary=BoUnDaRy')
        request.POST  # something read it first, e.g. middleware
        data, files = parse_multipart(request)
        self.assertEqual(data.get('name'), 'x')
