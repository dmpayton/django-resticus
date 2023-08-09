import warnings

from django.core.serializers.json import DjangoJSONEncoder
import types

from django.utils.functional import Promise

from .compat import json, force_text
from .iterators import iterlist


class JSONDecoder(json.JSONDecoder):
    pass


class JSONEncoder(DjangoJSONEncoder):
    def default(self, obj):
        if isinstance(obj, types.GeneratorType):
            return iterlist(obj)
        return super().default(obj)
