from django.utils.translation import gettext as _

from . import http
from .utils import patch_form

__all__ = [
    "ListModelMixin",
    "DetailModelMixin",
    "CreateModelMixin",
    "UpdateModelMixin",
    "DeleteModelMixin",
]


class ListModelMixin(object):
    def get(self, request, *args, **kwargs):
        """
        Returns a list of objects.
        """
        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset)

        orderby = self.request.GET.get("orderby", None)
        if orderby:
            if hasattr(queryset.model, orderby.lstrip("-")):
                queryset = queryset.order_by(orderby)

            else:
                msg = _("{} is not a valid sort parameter.".format(orderby))
                return http.Http400(reason=msg)

        queryset = self.paginate_queryset(queryset)

        response = {"data": self.serialize(queryset)}

        if self.paginator is not None:
            response.update(
                page=self.page.number,
                count=self.paginator.count,
                pages=self.paginator.num_pages,
                has_next_page=self.page.has_next(),
                has_previous_page=self.page.has_previous(),
            )
        return response


class DetailModelMixin(object):
    def get(self, request, *args, **kwargs):
        """
        Returns a single object.
        """
        self.object = self.get_object()
        return {"data": self.serialize(self.object)}


class CreateModelMixin(object):
    def put(self, request, *args, **kwargs):
        form = self.get_form(data=request.data, files=request.files)
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def post(self, request, *args, **kwargs):
        """
        Add new object.
        """
        return self.put(request, *args, **kwargs)

    def form_valid(self, form):
        data = super(CreateModelMixin, self).form_valid(form)
        return http.Http201(data)


class UpdateModelMixin(object):
    def put(self, request, *args, **kwargs):
        """
        Update existing object.
        """
        self.object = self.get_object()
        form = self.get_form(
            data=request.data, files=request.files, instance=self.object
        )
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)


class PatchModelMixin(object):
    def patch(self, request, *args, **kwargs):
        """
        Update existing object.
        """
        self.object = self.get_object()
        form = self.get_form(
            data=request.data, files=request.files, instance=self.object
        )
        form = patch_form(form)
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)


class DeleteModelMixin(object):
    def delete(self, request, *args, **kwargs):
        """
        Delete object.
        """
        self.object = self.get_object()
        self.object.delete()
        return http.Http204()
