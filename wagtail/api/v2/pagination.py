from collections import OrderedDict

from django.conf import settings
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _
from rest_framework.compat import coreapi, coreschema
from rest_framework.pagination import BasePagination
from rest_framework.response import Response

from .utils import BadRequestError


class WagtailPagination(BasePagination):
    offset_param = 'offset'
    offset_title = _('Offset')
    offset_description = _('Pagination offset.')

    limit_param = 'limit'
    limit_title = _('Limit')
    limit_description = _('Pagination limit.')

    def paginate_queryset(self, queryset, request, view=None):
        limit_max = getattr(settings, 'WAGTAILAPI_LIMIT_MAX', 20)

        try:
            offset = int(request.GET.get(self.offset_param, 0))
            if offset < 0:
                raise ValueError()
        except ValueError:
            raise BadRequestError("{} must be a positive integer".format(self.offset_param))

        try:
            limit_default = 20 if not limit_max else min(20, limit_max)
            limit = int(request.GET.get(self.limit_param, limit_default))
            if limit < 0:
                raise ValueError()
        except ValueError:
            raise BadRequestError("{} must be a positive integer".format(self.limit_param))

        if limit_max and limit > limit_max:
            raise BadRequestError(
                "limit cannot be higher than %d" % limit_max)

        start = offset
        stop = offset + limit

        self.view = view
        self.total_count = queryset.count()
        return queryset[start:stop]

    def get_paginated_response(self, data):
        data = OrderedDict([
            ('meta', OrderedDict([
                ('total_count', self.total_count),
            ])),
            ('items', data),
        ])
        return Response(data)

    def get_schema_fields(self, view):
        assert coreapi is not None, 'coreapi must be installed to use `get_schema_fields()`'
        assert coreschema is not None, 'coreschema must be installed to use `get_schema_fields()`'
        return [
            coreapi.Field(
                name=self.offset_param,
                required=False,
                location='query',
                schema=coreschema.Integer(
                    title=force_text(self.offset_title),
                    description=force_text(self.offset_description)
                )
            ),
            coreapi.Field(
                name=self.limit_param,
                required=False,
                location='query',
                schema=coreschema.Integer(
                    title=force_text(self.limit_title),
                    description=force_text(self.limit_description)
                )
            ),
        ]
