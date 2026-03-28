import pytest
from django.test import TestCase, override_settings
from django.urls import path
from resticus.views import Endpoint
from resticus.settings import api_settings
from resticus import generics
from resticus.schemas import SchemaGenerator, _serializer_to_schema, _model_field_to_schema
from resticus.serializers import Serializer
from tests.testapp.filters import BookFilter
from tests.testapp.models import Book, Author


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


class DocumentedView(generics.ListEndpoint):
    """A documented endpoint."""
    model = None
    documented = True

    def get_queryset(self):
        return []


class HiddenView(Endpoint):
    documented = False

    def get(self, request):
        return {}


class DetailView(generics.DetailEndpoint):
    model = None

    def get_object(self):
        return None


test_urlconf_patterns = [
    path('items/', DocumentedView.as_view(), name='item-list'),
    path('items/<int:pk>/', DetailView.as_view(), name='item-detail'),
    path('hidden/', HiddenView.as_view(), name='hidden'),
]


class FakeURLConf:
    urlpatterns = test_urlconf_patterns


class TestSchemaGeneratorTraversal(TestCase):
    def setUp(self):
        self.generator = SchemaGenerator(
            title='Test API',
            version='1.0',
            urlconf=FakeURLConf,
        )

    def test_documented_endpoint_appears_in_paths(self):
        schema = self.generator.get_schema()
        assert '/items/' in schema['paths']

    def test_undocumented_endpoint_excluded_from_paths(self):
        schema = self.generator.get_schema()
        assert '/hidden/' not in schema['paths']

    def test_schema_has_openapi_version(self):
        schema = self.generator.get_schema()
        assert schema['openapi'] == '3.1.0'

    def test_schema_has_info_block(self):
        schema = self.generator.get_schema()
        assert schema['info']['title'] == 'Test API'
        assert schema['info']['version'] == '1.0'

    def test_schema_has_security_schemes(self):
        schema = self.generator.get_schema()
        assert 'sessionAuth' in schema['components']['securitySchemes']

    def test_path_parameters_converted_to_openapi_style(self):
        schema = self.generator.get_schema()
        assert '/items/{pk}/' in schema['paths']
        params = schema['paths']['/items/{pk}/']['get']['parameters']
        assert any(p['name'] == 'pk' and p['in'] == 'path' for p in params)

    def test_int_path_converter_yields_integer_type(self):
        # DetailView uses <int:pk> — should produce type: integer, not string
        schema = self.generator.get_schema()
        params = schema['paths']['/items/{pk}/']['get']['parameters']
        pk_param = next(p for p in params if p['name'] == 'pk')
        assert pk_param['schema']['type'] == 'integer'

    def test_operation_id_present(self):
        schema = self.generator.get_schema()
        op = schema['paths']['/items/']['get']
        assert 'operationId' in op

    def test_operation_id_includes_url_name_and_method(self):
        schema = self.generator.get_schema()
        assert schema['paths']['/items/']['get']['operationId'] == 'item_list_get'
        assert schema['paths']['/items/{pk}/']['get']['operationId'] == 'item_detail_get'

    def test_responses_has_404_for_detail_endpoint(self):
        schema = self.generator.get_schema()
        responses = schema['paths']['/items/{pk}/']['get']['responses']
        assert '404' in responses

    def test_responses_no_404_for_list_endpoint(self):
        schema = self.generator.get_schema()
        responses = schema['paths']['/items/']['get']['responses']
        assert '404' not in responses


class FilteredView(generics.ListEndpoint):
    model = None
    filter_class = BookFilter

    def get_queryset(self):
        return []


filtered_urlconf_patterns = [
    path('books/', FilteredView.as_view(), name='book-list'),
]


class FakeFilteredURLConf:
    urlpatterns = filtered_urlconf_patterns


class TestFilterIntrospection(TestCase):
    def setUp(self):
        self.generator = SchemaGenerator(urlconf=FakeFilteredURLConf)

    def test_filter_fields_appear_as_query_params(self):
        schema = self.generator.get_schema()
        params = schema['paths']['/books/']['get']['parameters']
        param_names = [p['name'] for p in params]
        assert 'price' in param_names or any('price' in n for n in param_names)

    def test_filter_params_have_in_query(self):
        schema = self.generator.get_schema()
        params = schema['paths']['/books/']['get']['parameters']
        query_params = [p for p in params if p['in'] == 'query']
        assert len(query_params) > 0

    def test_filter_lookup_suffixes_are_separate_params(self):
        schema = self.generator.get_schema()
        params = schema['paths']['/books/']['get']['parameters']
        param_names = [p['name'] for p in params]
        # BookFilter has price__exact, price__lt, price__lte, price__gt, price__gte
        # Check that at least two price-related params exist
        price_params = [n for n in param_names if 'price' in n]
        assert len(price_params) >= 2

    def test_paginated_view_has_page_param(self):
        schema = self.generator.get_schema()
        params = schema['paths']['/books/']['get']['parameters']
        param_names = [p['name'] for p in params]
        assert 'page' in param_names

    def test_page_param_is_integer(self):
        schema = self.generator.get_schema()
        params = schema['paths']['/books/']['get']['parameters']
        page_param = next(p for p in params if p['name'] == 'page')
        assert page_param['schema']['type'] == 'integer'


class NonPaginatedView(generics.ListEndpoint):
    model = None
    paginate = False

    def get_queryset(self):
        return []


non_paginated_urlconf_patterns = [
    path('items/', NonPaginatedView.as_view(), name='item-list'),
]


class FakeNonPaginatedURLConf:
    urlpatterns = non_paginated_urlconf_patterns


class TestPaginationIntrospection(TestCase):
    def test_non_paginated_view_has_no_page_param(self):
        schema = SchemaGenerator(urlconf=FakeNonPaginatedURLConf).get_schema()
        params = schema['paths']['/items/']['get']['parameters']
        param_names = [p['name'] for p in params]
        assert 'page' not in param_names


from tests.testapp.forms import AuthorForm
from tests.testapp.views import AuthorList   # ListCreateEndpoint with form_class=AuthorForm


class GetOnlyFormView(Endpoint):
    """GET-only endpoint with a form_class."""
    form_class = AuthorForm

    def get(self, request):
        return {}


form_urlconf_patterns = [
    path('authors/', AuthorList.as_view(), name='author-list'),
    path('search/', GetOnlyFormView.as_view(), name='author-search'),
]


class FakeFormURLConf:
    urlpatterns = form_urlconf_patterns


class TestFormIntrospection(TestCase):
    def setUp(self):
        self.generator = SchemaGenerator(urlconf=FakeFormURLConf)
        self.schema = self.generator.get_schema()

    def test_post_endpoint_has_request_body(self):
        # AuthorList is a ListCreateEndpoint (has post)
        assert 'requestBody' in self.schema['paths']['/authors/']['post']

    def test_request_body_contains_form_fields(self):
        body = self.schema['paths']['/authors/']['post']['requestBody']
        props = body['content']['application/json']['schema']['properties']
        assert 'name' in props

    def test_get_only_form_fields_become_query_params(self):
        params = self.schema['paths']['/search/']['get']['parameters']
        param_names = [p['name'] for p in params]
        assert 'name' in param_names

    def test_get_only_form_params_have_in_query(self):
        params = self.schema['paths']['/search/']['get']['parameters']
        for p in params:
            if p['name'] == 'name':
                assert p['in'] == 'query'


class AuthRequiredView(Endpoint):
    login_required = True

    def get(self, request):
        return {}


class PerMethodAuthView(Endpoint):
    login_required = False

    def get(self, request):
        return {}

    def post(self, request):
        return {}


# Set login_required only on get
PerMethodAuthView.get.login_required = True


auth_urlconf_patterns = [
    path('secure/', AuthRequiredView.as_view(), name='secure'),
    path('mixed/', PerMethodAuthView.as_view(), name='mixed'),
]


class FakeAuthURLConf:
    urlpatterns = auth_urlconf_patterns


class TestAuthIntrospection(TestCase):
    def setUp(self):
        self.generator = SchemaGenerator(urlconf=FakeAuthURLConf)
        self.schema = self.generator.get_schema()

    def test_class_level_login_required_adds_security(self):
        get_op = self.schema['paths']['/secure/']['get']
        assert 'security' in get_op
        assert {'sessionAuth': []} in get_op['security']

    def test_unauthenticated_endpoint_has_no_security(self):
        post_op = self.schema['paths']['/mixed/']['post']
        assert 'security' not in post_op or post_op.get('security') == []

    def test_per_method_login_required_adds_security_to_that_method(self):
        get_op = self.schema['paths']['/mixed/']['get']
        assert 'security' in get_op
        assert {'sessionAuth': []} in get_op['security']

    def test_login_required_adds_401_and_403_responses(self):
        get_op = self.schema['paths']['/secure/']['get']
        assert '401' in get_op['responses']
        assert '403' in get_op['responses']

    def test_unauthenticated_endpoint_has_no_401_or_403(self):
        post_op = self.schema['paths']['/mixed/']['post']
        assert '401' not in post_op['responses']
        assert '403' not in post_op['responses']


class DeprecatedView(Endpoint):
    deprecated = True

    def get(self, request):
        return {}


deprecated_urlconf_patterns = [
    path('old/', DeprecatedView.as_view(), name='old-endpoint'),
]


class FakeDeprecatedURLConf:
    urlpatterns = deprecated_urlconf_patterns


class TestDeprecated(TestCase):
    def setUp(self):
        self.schema = SchemaGenerator(urlconf=FakeDeprecatedURLConf).get_schema()

    def test_deprecated_flag_on_operation(self):
        assert self.schema['paths']['/old/']['get']['deprecated'] is True

    def test_non_deprecated_view_has_no_deprecated_key(self):
        schema = SchemaGenerator(urlconf=FakeURLConf).get_schema()
        op = schema['paths']['/items/']['get']
        assert 'deprecated' not in op


from django.test import RequestFactory
from resticus.views import OpenAPISchemaView


class TestOpenAPISchemaView(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_returns_json_response(self):
        view = OpenAPISchemaView.as_view(
            title='Test',
            version='1.0',
            urlconf=FakeURLConf,
        )
        request = self.factory.get('/openapi.json')
        response = view(request)
        assert response.status_code == 200
        assert 'application/json' in response['Content-Type']

    def test_prefix_derived_from_request_path(self):
        import json
        view = OpenAPISchemaView.as_view(
            title='Test',
            version='1.0',
            urlconf=FakeURLConf,
        )
        request = self.factory.get('/api/2.0/openapi.json')
        response = view(request)
        schema = json.loads(response.content)
        assert schema['servers'] == [{'url': '/api/2.0/'}]

    def test_schema_view_is_not_documented(self):
        assert OpenAPISchemaView.documented is False


from resticus.views import DocsView


class TestDocsView(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _get(self, ui='scalar'):
        view = DocsView.as_view(
            ui=ui,
            schema_url='/api/2.0/openapi.json',
            title='Test API',
        )
        request = self.factory.get('/docs/')
        return view(request)

    def test_scalar_returns_html(self):
        response = self._get('scalar')
        assert response.status_code == 200
        assert 'text/html' in response['Content-Type']
        assert b'@scalar/api-reference' in response.content

    def test_swagger_returns_html(self):
        response = self._get('swagger')
        assert b'swagger-ui-bundle' in response.content

    def test_redoc_returns_html(self):
        response = self._get('redoc')
        assert b'redoc.standalone' in response.content

    def test_elements_returns_html(self):
        response = self._get('elements')
        assert b'stoplight/elements' in response.content

    def test_schema_url_is_embedded(self):
        response = self._get('scalar')
        assert b'/api/2.0/openapi.json' in response.content

    def test_title_is_embedded(self):
        response = self._get('scalar')
        assert b'Test API' in response.content

    def test_unknown_ui_raises(self):
        with pytest.raises((ValueError, KeyError)):
            self._get('nonexistent')

    def test_docs_view_is_not_documented(self):
        assert DocsView.documented is False


class InheritedDocView(generics.ListEndpoint):
    """Class docstring."""
    model = None
    # get() is inherited from ListEndpoint — do NOT define it here

    def get_queryset(self):
        return []


class OwnDocView(Endpoint):
    """Class docstring."""

    def get(self, request):
        """My own summary."""
        return {}


inherited_doc_urlconf_patterns = [
    path('inherited/', InheritedDocView.as_view(), name='inherited'),
    path('own/', OwnDocView.as_view(), name='own'),
]


class FakeInheritedDocURLConf:
    urlpatterns = inherited_doc_urlconf_patterns


class TaggedView(Endpoint):
    tags = ['custom']

    def get(self, request):
        return {}


tagged_urlconf_patterns = [
    path('monitors/', DocumentedView.as_view(), name='monitors'),
    path('monitors/<int:pk>/', DetailView.as_view(), name='monitor-detail'),
    path('tagged/', TaggedView.as_view(), name='tagged'),
]


class FakeTaggedURLConf:
    urlpatterns = tagged_urlconf_patterns


class TestInheritedSummary(TestCase):
    def setUp(self):
        self.generator = SchemaGenerator(urlconf=FakeInheritedDocURLConf)
        self.schema = self.generator.get_schema()

    def test_inherited_method_docstring_not_used(self):
        # get() is inherited from ListEndpoint; its docstring should NOT appear
        get_op = self.schema['paths']['/inherited/']['get']
        assert 'summary' not in get_op

    def test_own_method_docstring_is_used(self):
        # get() is defined directly on OwnDocView
        get_op = self.schema['paths']['/own/']['get']
        assert get_op.get('summary') == 'My own summary.'


class TestTags(TestCase):
    def setUp(self):
        self.generator = SchemaGenerator(urlconf=FakeTaggedURLConf)
        self.schema = self.generator.get_schema()

    def test_tag_auto_derived_from_first_path_segment(self):
        get_op = self.schema['paths']['/monitors/']['get']
        assert get_op.get('tags') == ['monitors']

    def test_tag_auto_derived_for_detail_path(self):
        get_op = self.schema['paths']['/monitors/{pk}/']['get']
        assert get_op.get('tags') == ['monitors']

    def test_class_tags_override_derived(self):
        get_op = self.schema['paths']['/tagged/']['get']
        assert get_op.get('tags') == ['custom']

    def test_no_tags_emitted_for_root_path(self):
        root_view = type('RootView', (Endpoint,), {'get': lambda self, r: {}})
        root_conf = type('Conf', (), {'urlpatterns': [path('', root_view.as_view())]})
        schema = SchemaGenerator(urlconf=root_conf).get_schema()
        # Root path '/' has no meaningful first segment — tags key must be absent
        op = list(schema['paths'].values())[0]['get']
        assert 'tags' not in op


# ---------------------------------------------------------------------------
# Serializer introspection
# ---------------------------------------------------------------------------

class BookSerializer(Serializer):
    fields = [
        'id',
        'title',
        'isbn',
        'price',
        'author',  # ForeignKey → int (Author PK is AutoField)
        ('display', lambda b: str(b)),
    ]


class NestedSerializer(Serializer):
    fields = ['name']


class ParentSerializer(Serializer):
    fields = [
        'id',
        ('nested', NestedSerializer),
    ]


class TestModelFieldToSchema(TestCase):
    def test_char_field_is_string(self):
        field = Book._meta.get_field('title')
        assert _model_field_to_schema(field) == {'type': 'string'}

    def test_decimal_field_is_number(self):
        field = Book._meta.get_field('price')
        assert _model_field_to_schema(field) == {'type': 'number'}

    def test_foreign_key_returns_pk_type(self):
        field = Book._meta.get_field('author')
        # Author PK is an AutoField → integer
        assert _model_field_to_schema(field) == {'type': 'integer'}


class TestSerializerToSchema(TestCase):
    def test_string_field_resolved_from_model(self):
        props = _serializer_to_schema(BookSerializer, model=Book)
        assert props['title'] == {'type': 'string'}

    def test_decimal_field_resolved(self):
        props = _serializer_to_schema(BookSerializer, model=Book)
        assert props['price'] == {'type': 'number'}

    def test_fk_field_resolved_to_pk_type(self):
        props = _serializer_to_schema(BookSerializer, model=Book)
        assert props['author'] == {'type': 'integer'}

    def test_callable_field_is_any_type(self):
        props = _serializer_to_schema(BookSerializer, model=Book)
        assert props['display'] == {}

    def test_nested_serializer_becomes_object(self):
        props = _serializer_to_schema(ParentSerializer, model=Author)
        assert props['nested']['type'] == 'object'
        assert 'name' in props['nested']['properties']

    def test_no_model_string_field_is_any_type(self):
        props = _serializer_to_schema(BookSerializer, model=None)
        assert props['title'] == {}


class BookListView(generics.ListEndpoint):
    """List all books."""
    model = Book
    serializer_class = BookSerializer
    paginate = True


class BookDetailView(generics.DetailEndpoint):
    """Retrieve a single book."""
    model = Book
    serializer_class = BookSerializer
    lookup_field = 'isbn'


serializer_urlconf_patterns = [
    path('books/', BookListView.as_view(), name='book-list'),
    path('books/<str:isbn>/', BookDetailView.as_view(), name='book-detail'),
]


class FakeSerializerURLConf:
    urlpatterns = serializer_urlconf_patterns


class TestResponseSchema(TestCase):
    def setUp(self):
        self.generator = SchemaGenerator(urlconf=FakeSerializerURLConf)
        self.schema = self.generator.get_schema()

    def test_list_response_has_data_array(self):
        response = self.schema['paths']['/books/']['get']['responses']['200']
        props = response['content']['application/json']['schema']['properties']
        assert props['data']['type'] == 'array'

    def test_list_response_items_have_fields(self):
        response = self.schema['paths']['/books/']['get']['responses']['200']
        props = response['content']['application/json']['schema']['properties']
        item_props = props['data']['items']['properties']
        assert 'title' in item_props
        assert 'price' in item_props

    def test_paginated_list_includes_pagination_fields(self):
        response = self.schema['paths']['/books/']['get']['responses']['200']
        props = response['content']['application/json']['schema']['properties']
        assert 'page' in props
        assert 'count' in props
        assert 'pages' in props
        assert 'has_next_page' in props
        assert 'has_previous_page' in props

    def test_detail_response_has_data_object(self):
        response = self.schema['paths']['/books/{isbn}/']['get']['responses']['200']
        props = response['content']['application/json']['schema']['properties']
        assert props['data']['type'] == 'object'

    def test_detail_response_data_has_item_fields(self):
        response = self.schema['paths']['/books/{isbn}/']['get']['responses']['200']
        props = response['content']['application/json']['schema']['properties']
        item_props = props['data']['properties']
        assert 'title' in item_props
        assert 'price' in item_props

    def test_view_without_serializer_has_no_response_content(self):
        # DocumentedView has no serializer_class
        schema = SchemaGenerator(urlconf=FakeURLConf).get_schema()
        response = schema['paths']['/items/']['get']['responses']['200']
        assert 'content' not in response
