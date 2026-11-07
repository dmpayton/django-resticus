import base64

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError

from resticus import generics
from resticus.auth import login_required, BasicHttpAuth
from resticus.exceptions import HttpError
from resticus.http import Http201, Http403, Http404, Http400
from resticus.serializers import serialize
from resticus.views import Endpoint

from .models import *
from .filters import *
from .forms import *

__all__ = ['AuthorList', 'AuthorDetail', 'PublisherList', 'PublisherDetail',
    'ReadOnlyPublisherList', 'BookList', 'BookDetail', 'FailsIntentionally',
    'WildcardHandler', 'EchoView', 'ErrorRaisingView', 'BasicAuthEndpoint']
__all__ += ['QuerysetPublisherDetail']


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


class QuerysetPublisherDetail(generics.DetailEndpoint):
    """Declares only a queryset, no model."""
    queryset = Publisher.objects.all()


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


__all__ += ['RaisesValidationError']


class RaisesValidationError(Endpoint):
    """Raises a Django ValidationError for dispatch to turn into a 400."""

    ERRORS = {
        'single': lambda: ValidationError("'%(value)s' is bad.", params={'value': 'x'}),
        'list': lambda: ValidationError(['one', 'two']),
        'dict': lambda: ValidationError({'name': ['Required.'], NON_FIELD_ERRORS: ['Clash.']}),
    }

    def get(self, request):
        raise self.ERRORS[request.GET['kind']]()
