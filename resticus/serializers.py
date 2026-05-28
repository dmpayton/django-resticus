import builtins
import inspect
import json

from django.contrib.gis.geos import GEOSGeometry
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.db import models
from django.utils.functional import cached_property

__all__ = ["serialize", "serialize_object", "flatten"]


def _resolve_tuple_field(instance, key, value):
    """Resolve a (key, value) tuple field descriptor against an instance.

    Handles three forms:
      (key, SerializerSubclass)  — nested serialization via that class
      (key, callable)            — calls callable(instance)
      (key, dict)                — recursive serialize() with dict kwargs
    """
    if callable(value):
        if inspect.isclass(value) and issubclass(value, Serializer):
            return value(getattr(instance, key, None)).serialize()
        return value(instance)
    elif isinstance(value, dict):
        try:
            return serialize(getattr(instance, key, None), **value)
        except ObjectDoesNotExist:
            return None


def serialize_object(
    instance, fields=None, include=None, exclude=None, fixup=None, request=None
):
    """Serialize any Python object with attribute access.

    Works on SimpleNamespace, dataclasses, namedtuples, or any object
    whose fields are reachable via getattr. String fields are read with
    getattr(instance, name, None); tuple fields are handled by
    _resolve_tuple_field.

    For Django model instances prefer serialize_model, which additionally
    handles _meta field resolution, FileField, GEOSGeometry, and Manager.
    """
    fields = list(fields or [])

    if exclude is not None:
        fields = [f for f in fields if (f if isinstance(f, str) else f[0]) not in exclude]

    if include is not None:
        for attr in include:
            if isinstance(attr, (tuple, str)):
                fields.append(attr)

    data = {}
    for field in fields:
        if isinstance(field, str):
            data[field] = getattr(instance, field, None)
        elif isinstance(field, tuple):
            key, value = field
            data[key] = _resolve_tuple_field(instance, key, value)

    if fixup:
        data = fixup(instance, data)

    return data


def serialize_model(
    instance, fields=None, include=None, exclude=None, fixup=None, request=None
):
    def getfield(name):
        try:
            return instance._meta.concrete_model._meta.get_field(name)
        except FieldDoesNotExist:
            return None

    if fields is None:
        fields = [
            field.name for field in instance._meta.concrete_model._meta.local_fields
        ]
    else:
        fields = list(fields)

    if exclude is not None:
        fields = [f for f in fields if (f if isinstance(f, str) else f[0]) not in exclude]

    if include is not None:
        for attr in include:
            if isinstance(attr, (tuple, str)):
                fields.append(attr)

    data = {}
    for field in fields:
        if isinstance(field, str):
            model_field = getfield(field)
            try:
                value = getattr(
                    instance, model_field and getattr(model_field, "attname", None) or field
                )
            except ObjectDoesNotExist:
                value = None
            if isinstance(model_field, models.FileField):
                value = value.url if value else None
                if value is not None and request is not None:
                    value = request.build_absolute_uri(value)
                data[field] = value
            elif isinstance(value, GEOSGeometry):
                data[field] = json.loads(value.geojson)
            elif isinstance(value, models.Manager):
                data[field] = [item.pk for item in value.all()]
            else:
                data[field] = value
        elif isinstance(field, tuple):
            key, value = field
            data[key] = _resolve_tuple_field(instance, key, value)

    if fixup:
        data = fixup(instance, data)

    return data


def serialize(
    src, fields=None, include=None, exclude=None, fixup=None, request=None, filter=None
):
    """Serialize Model or a QuerySet instance to Python primitives.
    By default, all the model fields (and only the model fields) are
    serialized. If the field is a Python primitive, it is serialized as such,
    otherwise it is converted to string in utf-8 encoding.
    If `fields` is specified, it is a list of attribute descriptions to be
    serialized, replacing the default (all model fields). If `include` is
    specified, it is a list of attribute descriptions to add to the default
    list. If `exclude` is specified, it is a list of attribute descriptions
    to remove from the default list.
    Each attribute description can be either:
      * a string - includes a correspondingly named attribute of the object
        being serialized (eg. `name`, or `created_at`); this can be a
        model field, a property, class variable or anything else that's
        an attribute on the instance
      * a tuple, where the first element is a string key and the second
        is a function taking one argument - function will be run with the
        object being serialized as the argument, and the function result will
        be included in the result, with the key being the first tuple element
      * a tuple, where the first element is a related model attribute name
        and the second is a dictionary or `Serializer` class - related model
        instance(s) will be serialized recursively and added as sub-object(s)
        to the object being serialized; the dictionary may specify `fields`,
        `include`, `exclude` and `fixup` options for the related models following
        the same semantics as for the object being serialized.
    The `fixup` argument, if defined, is a function taking two arguments, the
    object being serialized, and the serialization result dict, and returning
    the modified serialization result. It's useful in cases where it's
    neccessary to modify the result of the automatic serialization, but its
    use is discouraged if the same result can be obtained through the
    attribute descriptions.

    Example::
        serialize(obj, fields=[
            'name',   # obj.name
            'dob',    # obj.dob
            ('age', lambda obj: date.today() - obj.dob),
            ('jobs', dict(   # for job in obj.jobs.all()
                fields=[
                    'title',  # job.title
                    'from',   # job.from
                    'to',     # job.to,
                    ('duration', lambda job: job.to - job.from),
                ]
            )),
            ('profile', ProfileSerializer),
        ])
    Returns: a dict (if a single model instance was serialized) or a list
    od dicts (if a QuerySet was serialized) with the serialized data. The
    data returned is suitable for JSON serialization using Django's JSON
    serializator.
    """

    def subs(subsrc):
        return serialize(
            subsrc,
            fields=fields,
            include=include,
            exclude=exclude,
            fixup=fixup,
            request=request,
            filter=filter,
        )

    if isinstance(src, models.Manager):
        return [subs(instance) for instance in builtins.filter(filter, src.all())]

    elif isinstance(src, (list, set, models.query.QuerySet)):
        return [subs(instance) for instance in builtins.filter(filter, src)]

    elif isinstance(src, dict):
        return dict((key, subs(value)) for key, value in src.items())

    elif isinstance(src, models.Model):
        return serialize_model(
            src,
            fields=fields,
            include=include,
            exclude=exclude,
            fixup=fixup,
            request=request,
        )

    elif fields is not None and hasattr(src, '__dict__'):
        return serialize_object(
            src,
            fields=fields,
            include=include,
            exclude=exclude,
            fixup=fixup,
            request=request,
        )

    else:
        return src


def flatten(attname):
    """Fixup helper for serialize.
    Given an attribute name, returns a fixup function suitable for serialize()
    that will pull all items from the sub-dict and into the main dict. If
    any of the keys from the sub-dict already exist in the main dict, they'll
    be overwritten.
    """

    def fixup(obj, data):
        for k, v in data[attname].items():
            data[k] = v
        del data[attname]
        return data

    return fixup


class Serializer:
    fields = None
    include = None
    exclude = None
    fixup = None
    filter = None

    def __init__(
        self,
        source,
        fields=None,
        include=None,
        exclude=None,
        fixup=None,
        request=None,
        filter=None,
    ):
        self.source = source
        self.fields = fields or self.fields
        self.include = include or self.include
        self.exclude = exclude or self.exclude
        self.fixup = fixup or self.fixup
        self.request = request
        self.filter = filter or self.filter

    @cached_property
    def data(self):
        return self.serialize()

    def handle_fixup(self, instance, data):
        if self.fixup is not None:
            return self.fixup(instance, data)
        return data

    def serialize(self):
        return serialize(
            self.source,
            fields=self.fields,
            include=self.include,
            exclude=self.exclude,
            fixup=self.handle_fixup,
            request=self.request,
            filter=self.filter,
        )
