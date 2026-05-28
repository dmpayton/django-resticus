from django.core import paginator
from django.core.exceptions import ImproperlyConfigured
from django.forms.models import modelform_factory
from django.utils.translation import gettext as _

from . import exceptions, http, mixins
from .serializers import Serializer
from .settings import api_settings
from .utils import filterset_factory
from .views import Endpoint

__all__ = [
    "GenericEndpoint",
    "CreateEndpoint",
    "ListEndpoint",
    "DetailEndpoint",
    "UpdateEndpoint",
    "DeleteEndpoint",
    "ListCreateEndpoint",
    "DetailUpdateEndpoint",
    "DetailDeleteEndpoint",
    "DetailUpdateDeleteEndpoint",
]


class GenericEndpoint(Endpoint):
    model = None

    serializer_class = Serializer
    fields = None

    lookup_field = "pk"
    lookup_url_kwarg = None

    filter_class = None
    form_class = None
    queryset = None

    paginate = api_settings.PAGINATE
    page_size = api_settings.PAGE_SIZE
    page_query_param = api_settings.PAGE_QUERY_PARAM
    page_size_query_param = api_settings.PAGE_SIZE_QUERY_PARAM
    max_page_size = api_settings.MAX_PAGE_SIZE

    def get_queryset(self):
        if self.queryset is not None:
            return self.queryset._clone()

        if self.model is not None:
            return self.model._default_manager.all()

        msg = _(
            '{0} must either define "model" or "queryset", or '
            'override "get_queryset()"'
        )
        raise ImproperlyConfigured(msg.format(self.__class__.__name__))

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        try:
            lookup = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        except KeyError:
            msg = _('Lookup field "{0}" was not provided in view ' 'kwargs to "{1}"')
            raise ImproperlyConfigured(
                msg.format(lookup_url_kwarg, self.__class__.__name__)
            )

        try:
            obj = queryset.get(**lookup)
        except self.model.DoesNotExist:
            raise exceptions.NotFound(_("Resource not found"))

        self.check_object_permissions(self.request, obj)
        return obj

    def get_filter_class(self):
        if self.filter_class is not None:
            return self.filter_class

    def filter_queryset(self, queryset):
        FilterClass = self.get_filter_class()
        if FilterClass is not None:
            filter = FilterClass(self.request.GET, queryset=queryset)
            return filter.qs
        return queryset

    def paginate_queryset(self, queryset):
        self.paginator = None
        if self.paginate:
            try:
                page_size = int(self.request.GET[self.page_size_query_param])
                page_size = max(min(page_size, self.max_page_size), 1)
            except (KeyError, ValueError):
                page_size = self.page_size

            if not queryset.ordered:
                queryset = queryset.order_by('pk')

            self.paginator = paginator.Paginator(
                object_list=queryset, per_page=page_size, allow_empty_first_page=True
            )

            try:
                page_number = int(self.request.GET.get(self.page_query_param, 1))
                self.page = self.paginator.page(page_number)
            except (ValueError, paginator.InvalidPage):
                raise exceptions.NotFound(_("Invalid page."))

            return self.page.object_list
        return queryset

    def get_form_class(self):
        if self.form_class is not None:
            return self.form_class
        return modelform_factory(self.model, fields=self.fields or "__all__")

    def get_form(self, data=None, files=None, **kwargs):
        FormClass = self.get_form_class()
        return FormClass(data=data, files=files, **kwargs)

    def form_valid(self, form):
        self.object = form.save()
        return {"data": self.serialize(self.object)}

    def form_invalid(self, form):
        raise exceptions.ValidationError(form=form)

    def get_serializer_class(self):
        return self.serializer_class

    def serialize(self, source, fields=None, include=None, exclude=None, fixup=None):
        serializer = self.get_serializer_class()
        return serializer(
            source,
            fields=fields or self.fields,
            include=include,
            exclude=exclude,
            fixup=fixup,
            request=self.request,
        ).data


class CreateEndpoint(mixins.CreateModelMixin, GenericEndpoint):
    pass


class ListEndpoint(mixins.ListModelMixin, GenericEndpoint):
    pass


class DetailEndpoint(mixins.DetailModelMixin, GenericEndpoint):
    pass


class UpdateEndpoint(mixins.UpdateModelMixin, mixins.PatchModelMixin, GenericEndpoint):
    pass


class DeleteEndpoint(mixins.DeleteModelMixin, GenericEndpoint):
    pass


class ListCreateEndpoint(
    mixins.ListModelMixin, mixins.CreateModelMixin, GenericEndpoint
):
    pass


class DetailUpdateEndpoint(
    mixins.DetailModelMixin,
    mixins.UpdateModelMixin,
    mixins.PatchModelMixin,
    GenericEndpoint,
):
    pass


class DetailDeleteEndpoint(
    mixins.DetailModelMixin, mixins.DeleteModelMixin, GenericEndpoint
):
    pass


class DetailUpdateDeleteEndpoint(
    mixins.DetailModelMixin,
    mixins.UpdateModelMixin,
    mixins.PatchModelMixin,
    mixins.DeleteModelMixin,
    GenericEndpoint,
):
    pass
