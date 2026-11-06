from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.db.models.query import QuerySet
from django.test import TestCase

from resticus.compat import json

from .client import ApiClient, debug
from .testapp.models import Publisher, Author, Book


class TestModelViews(TestCase):
    def setUp(self):
        self.client = ApiClient()
        self.publisher = Publisher.objects.create(name='User Foo')
        self.author = Author.objects.create(name='User Foo')
        self.book = self.author.books.create(author=self.author, title='Book',
            isbn='1234', price=Decimal('10.0'), publisher=self.publisher)

    def test_publisher_list(self):
        """Excercise listing objects via ListEndpoint"""

        r = self.client.get('publisher_list')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json['data']), 1)
        self.assertEqual(r.json['data'][0]['id'], self.publisher.id)

    def test_publisher_create(self):
        """Excercise creating objects via ListEndpoint"""

        r = self.client.post('publisher_list', data=json.dumps({
            'name': 'Another Publisher'
        }), content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertTrue(Publisher.objects.filter(pk=r.json['data']['id']).exists())

    def test_publisher_details(self):
        """Excercise getting a single object details via DetailEndpoint"""

        r = self.client.get('publisher_detail', pk=self.publisher.id)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['data']['id'], self.publisher.id)

    def test_publisher_update(self):
        """Excercise updating an object via POST via DetailEndpoint"""

        r = self.client.put('publisher_detail', pk=self.publisher.id,
            content_type='application/json', data=json.dumps({
                'name': 'Changed Name'
            }))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['data']['id'], self.publisher.id)
        p = Publisher.objects.get(id=self.publisher.id)
        self.assertEqual(p.name, 'Changed Name')

    def test_publisher_delete(self):
        """Excercise deleting an object via DetailEndpoint"""

        r = self.client.delete('publisher_detail', pk=self.publisher.id)
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Publisher.objects.exists())

    def test_readonly_publisher_list_denies_creation(self):
        """Excercise method whitelist in ListEndpoint"""

        r = self.client.post('readonly_publisher_list', data=json.dumps({
            'name': 'Another Publisher'
        }), content_type='application/json')
        self.assertEqual(r.status_code, 405)

    def test_book_details(self):
        """Excercise using custom lookup_field on a DetailEndpoint"""

        r = self.client.get('book_detail', isbn=self.book.isbn)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['data']['id'], self.book.id)

    def test_author_create_invalid(self):
        """Test the form validation errors"""
        r = self.client.post('author_list', {})
        self.assertEqual(r.status_code, 400)


class TestLookupNotFound(TestCase):
    """A lookup value the field can't take answers the same 404 as a missing object."""

    def setUp(self):
        self.client = ApiClient()
        self.publisher = Publisher.objects.create(name='User Foo')

    def assert_not_found(self, r):
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json['errors']['detail'][0]['message'], 'Resource not found')

    def test_missing_pk_is_404(self):
        self.assert_not_found(self.client.get('publisher_detail_str', pk=self.publisher.id + 1000))

    def test_unparseable_pk_is_404(self):
        self.assert_not_found(self.client.get('publisher_detail_str', pk='abc'))

    def test_validation_error_from_lookup_is_404(self):
        # e.g. a UUIDField or DateField rejecting the value in to_python
        with mock.patch.object(QuerySet, 'get', side_effect=ValidationError('bad')):
            self.assert_not_found(self.client.get('publisher_detail_str', pk=self.publisher.id))

    def test_queryset_only_endpoint_is_404(self):
        # An endpoint may declare `queryset` without `model`.
        for pk in ('abc', self.publisher.id + 1000):
            self.assert_not_found(self.client.get('publisher_detail_queryset', pk=pk))

    def test_valid_pk_still_200(self):
        r = self.client.get('publisher_detail_str', pk=self.publisher.id)
        self.assertEqual(r.status_code, 200)
