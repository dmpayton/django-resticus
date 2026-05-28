import base64
from django.test import TestCase
from resticus.auth import TokenAuth
from resticus.compat import json, get_user_model
from .client import ApiClient, debug
from .testapp.models import Publisher, Author, Book


class TestAuth(TestCase):
    client_class = ApiClient

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='foo',
            password='bar'
        )
        self.token = TokenAuth.get_token_model().objects.create(user=self.user)

    def test_session_login_success(self):
        """Test that correct username/password login succeeds"""
        r = self.client.post('session_auth', data={
            'username': 'foo', 'password': 'bar',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['data']['username'], 'foo')

    def test_session_login_failure(self):
        """Test that incorrect username/password login fails"""
        r = self.client.post('session_auth', data={
            'username': 'nonexistent', 'password': 'pwd',
        })
        self.assertEqual(r.status_code, 403)

    def test_session_auth_success(self):
        """Test that the Session Auth succeeds"""
        self.client.login(username='foo', password='bar')
        r = self.client.get('session_auth')
        self.assertEqual(r.status_code, 200)

    def test_session_auth_failure(self):
        """Test that the Session Auth fails"""
        r = self.client.get('session_auth')
        self.assertEqual(r.status_code, 403)

    def test_basic_auth_challenge(self):
        """Test that HTTP Basic Auth challenge is issued"""
        r = self.client.get('basic_auth')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r['WWW-Authenticate'], 'Basic realm="api"')

    def test_basic_auth_success(self):
        """Test that HTTP Basic Auth succeeds"""
        r = self.client.get('basic_auth', extra={
            'HTTP_AUTHORIZATION': 'Basic {0}'.format(
                base64.b64encode(b'foo:bar').decode('ascii')),
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['id'], self.user.id)

    def test_basic_auth_failure(self):
        """Test that HTTP Basic Auth fails"""
        r = self.client.get('basic_auth', extra={
            'HTTP_AUTHORIZATION': 'Basic {0}'.format(
                base64.b64encode(b'nonexistent:pwd').decode('ascii')),
        })
        self.assertEqual(r.status_code, 401)

    def test_basic_auth_invalid_auth_payload(self):
        """Test that invalid Basic Auth payload doesn't crash the pasrser"""
        r = self.client.get('basic_auth', extra={
            'HTTP_AUTHORIZATION': 'Basic xyz',
        })
        self.assertEqual(r.status_code, 401)

    def test_token_auth_challenge(self):
        """Test that Token Auth challenge is issued"""
        r = self.client.get('token_auth')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r['WWW-Authenticate'], 'Token')

    def test_token_login_success(self):
        """Test that correct username/password login succeeds"""
        r = self.client.post('token_auth', data={
            'username': 'foo', 'password': 'bar',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['data']['api_token'], self.token.key)

    def test_token_login_failure(self):
        """Test that incorrect username/password login fails"""
        r = self.client.post('token_auth', data={
            'username': 'nonexistent', 'password': 'pwd',
        })
        self.assertEqual(r.status_code, 401)

    @debug
    def test_token_auth_success(self):
        """Test that the Session Auth succeeds"""
        self.client.login(username='foo', password='bar')
        r = self.client.get('token_auth', extra={
            'HTTP_AUTHORIZATION': 'Token {0}'.format(self.token.key)
        })
        self.assertEqual(r.status_code, 200)

    def test_token_auth_failure(self):
        """Test that the Session Auth fails"""
        r = self.client.get('token_auth', extra={
            'HTTP_AUTHORIZATION': 'Token faketoken'
        })
        self.assertEqual(r.status_code, 401)
