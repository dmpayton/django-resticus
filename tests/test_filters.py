from decimal import Decimal

from django.test import TestCase
from resticus.compat import json

from .client import ApiClient, debug
from .testapp.models import Publisher, Author, Book


class TestEndpoint(TestCase):
    client_class = ApiClient

    def setUp(self):
        self.client = ApiClient()
        self.author = Author.objects.create(name='Author Foo')
        self.publisher = Publisher.objects.create(name='Publisher Foo')
        self.book1 = self.author.books.create(author=self.author, title='Book 1',
            isbn='1234', price=Decimal('10.0'), publisher=self.publisher)
        self.book2 = self.author.books.create(author=self.author, title='Book 2',
            isbn='5678', price=Decimal('20.0'), publisher=self.publisher)

    def test_filter_endpoint(self):
        """Exercise a simple GET request"""

        r = self.client.get('book_list', data={'author': self.author.pk})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json['data']), 2)

    def test_filter_endpoint_empty(self):
        """Exercise a simple GET request"""

        r = self.client.get('book_list', data={'price__gte': '20'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json['data']), 1)
