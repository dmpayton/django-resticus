from django.urls import path
from resticus.views import SessionAuthEndpoint, TokenAuthEndpoint

from .views import *

urlpatterns = [
    path('auth/', SessionAuthEndpoint.as_view(),
        name='session_auth'),
    path('auth/basic/', BasicAuthEndpoint.as_view(),
        name='basic_auth'),
    path('auth/token/', TokenAuthEndpoint.as_view(),
        name='token_auth'),

    path('authors/', AuthorList.as_view(),
        name='author_list'),
    path('authors/<int:author_id>', AuthorDetail.as_view(),
        name='author_detail'),

    path('publishers/', PublisherList.as_view(),
        name='publisher_list'),
    path('publishers-ready-only/', ReadOnlyPublisherList.as_view(),
        name='readonly_publisher_list'),
    path('publishers/<int:pk>', PublisherDetail.as_view(),
        name='publisher_detail'),

    path('books/', BookList.as_view(), name='book_list'),
    path('books/<int:isbn>', BookDetail.as_view(),
        name='book_detail'),

    path('fail-view/', FailsIntentionally.as_view(),
        name='fail_view'),
    path('echo-view/', EchoView.as_view(),
        name='echo_view'),
    path('csrf-probe/', CsrfProbe.as_view(), name='csrf_probe'),
    path('error-raising-view/', ErrorRaisingView.as_view(),
        name='error_raising_view'),
    path('.*', WildcardHandler.as_view()),
]
