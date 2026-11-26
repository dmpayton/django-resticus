import base64

from resticus import generics
from resticus.auth import login_required, BasicHttpAuth, TokenAuth
from resticus.exceptions import HttpError
from resticus.http import Http201, Http403, Http404, Http400
from resticus.serializers import serialize
from resticus.views import Endpoint

from .models import *
from .filters import *
from .forms import *

__all__ = ['AuthorList', 'AuthorDetail', 'PublisherList', 'PublisherDetail',
    'ReadOnlyPublisherList', 'BookList', 'BookDetail', 'FailsIntentionally',
    'WildcardHandler', 'EchoView', 'ErrorRaisingView', 'BasicAuthEndpoint',
    'CsrfProbe']


class AuthorList(generics.ListCreateEndpoint):
    model = Author
    form_class = AuthorForm


class AuthorDetail(generics.DetailUpdateDeleteEndpoint):
    model = Author
    form_class = AuthorForm
    lookup_url_kwarg = 'author_id'


class PublisherList(generics.ListCreateEndpoint):
    model = Publisher


class PublisherDetail(generics.DetailUpdateDeleteEndpoint):
    model = Publisher


class ReadOnlyPublisherList(generics.DetailEndpoint):
    model = Publisher


class BookList(generics.ListEndpoint):
    model = Book
    filter_class = BookFilter
    streaming = True


class BookDetail(generics.DetailEndpoint):
    model = Book
    lookup_field = 'isbn'


class FailsIntentionally(Endpoint):
    def get(self, request):
        raise Exception("I'm being a bad view")


class WildcardHandler(Endpoint):
    def dispatch(self, request, *args, **kwargs):
        return Http404('no such resource: %s %s' % (
            request.method, request.path))


class EchoView(Endpoint):
    def post(self, request):
        return {
            'headers': dict((k, str(v)) for k, v in request.META.items()),
            'raw_data': base64.b64encode(request.raw_data).decode('ascii')
        }

    def get(self, request):
        return self.post(request)

    def put(self, request):
        return self.post(request)


class ErrorRaisingView(Endpoint):
    def get(self, request):
        raise HttpError(400, 'raised error')


class BasicAuthEndpoint(Endpoint):
    authentication_classes = (BasicHttpAuth,)

    @login_required
    def get(self, request):
        return serialize(request.user)


class CsrfProbe(Endpoint):
    authentication_classes = (TokenAuth, BasicHttpAuth)

    def get(self, request):
        user = request.user
        data = request.data if hasattr(request.data, 'get') else {}
        return {
            'username': user.username if user.is_authenticated else None,
            'name': data.get('name'),
        }

    post = put = patch = delete = get
