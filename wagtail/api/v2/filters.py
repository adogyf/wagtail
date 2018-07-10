from django.conf import settings
from django.db import models
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _
from rest_framework.compat import coreapi, coreschema
from rest_framework.filters import BaseFilterBackend
from taggit.managers import TaggableManager

from wagtail.core import hooks
from wagtail.core.models import Page
from wagtail.search.backends import get_search_backend
from wagtail.search.backends.base import FilterFieldError, OrderByFieldError

from .utils import BadRequestError, pages_for_site, parse_boolean


class FieldsFilter(BaseFilterBackend):
    base_description = _('Filter results using an exact match.')
    taggable_description = _('Filter results using a comma-separated list of tags.')

    def filter_queryset(self, request, queryset, view):
        """
        This performs field level filtering on the result set
        Eg: ?title=James Joyce
        """
        fields = set(view.get_available_fields(queryset.model, db_fields_only=True))

        for field_name, value in request.GET.items():
            if field_name in fields:
                try:
                    field = queryset.model._meta.get_field(field_name)
                except LookupError:
                    field = None

                # Convert value into python
                try:
                    if isinstance(field, (models.BooleanField, models.NullBooleanField)):
                        value = parse_boolean(value)
                    elif isinstance(field, (models.IntegerField, models.AutoField)):
                        value = int(value)
                except ValueError as e:
                    raise BadRequestError("field filter error. '%s' is not a valid value for %s (%s)" % (
                        value,
                        field_name,
                        str(e)
                    ))

                if isinstance(field, TaggableManager):
                    for tag in value.split(','):
                        queryset = queryset.filter(**{field_name + '__name': tag})

                    # Stick a message on the queryset to indicate that tag filtering has been performed
                    # This will let the do_search method know that it must raise an error as searching
                    # and tag filtering at the same time is not supported
                    queryset._filtered_by_tag = True
                else:
                    queryset = queryset.filter(**{field_name: value})

        return queryset

    def get_schema_fields(self, view):
        assert coreapi is not None, 'coreapi must be installed to use `get_schema_fields()`'
        assert coreschema is not None, 'coreschema must be installed to use `get_schema_fields()`'
        schema_fields = []
        if hasattr(view, 'model'):
            fields = set(view.get_available_fields(view.model, db_fields_only=True))
            for field in fields:
                if isinstance(field, (models.BooleanField, models.NullBooleanField)):
                    schema_type = coreschema.Boolean
                elif isinstance(field, (models.IntegerField, models.AutoField)):
                    schema_type = coreschema.Integer
                else:
                    schema_type = coreschema.String

                description = self.base_description
                if isinstance(field, TaggableManager):
                    description = self.taggable_description

                title = _(field.name.title())

                schema_field = coreapi.Field(
                    name=field.name,
                    required=False,
                    location='query',
                    schema=schema_type(
                        title=force_text(title),
                        description=force_text(description)
                    )
                )
                schema_fields.append(schema_field)
        return schema_fields


class OrderingFilter(BaseFilterBackend):
    query_param = 'order'
    title = _('Ordering')
    description = _('Which field to use when ordering the results.')

    def filter_queryset(self, request, queryset, view):
        """
        This applies ordering to the result set
        Eg: ?order=title

        It also supports reverse ordering
        Eg: ?order=-title

        And random ordering
        Eg: ?order=random
        """
        if self.query_param in request.GET:
            order_by = request.GET[self.query_param]

            # Random ordering
            if order_by == 'random':
                # Prevent ordering by random with offset
                if 'offset' in request.GET:
                    raise BadRequestError("random ordering with offset is not supported")

                return queryset.order_by('?')

            # Check if reverse ordering is set
            if order_by.startswith('-'):
                reverse_order = True
                order_by = order_by[1:]
            else:
                reverse_order = False

            # Add ordering
            if order_by in view.get_available_fields(queryset.model):
                queryset = queryset.order_by(order_by)
            else:
                # Unknown field
                raise BadRequestError("cannot order by '%s' (unknown field)" % order_by)

            # Reverse order
            if reverse_order:
                queryset = queryset.reverse()

        return queryset


    def get_schema_fields(self, view):
        assert coreapi is not None, 'coreapi must be installed to use `get_schema_fields()`'
        assert coreschema is not None, 'coreschema must be installed to use `get_schema_fields()`'
        return [
            coreapi.Field(
                name=self.query_param,
                required=False,
                location='query',
                schema=coreschema.String(
                    title=force_text(self.title),
                    description=force_text(self.description)
                )
            )
        ]


class SearchFilter(BaseFilterBackend):
    query_param = 'search'
    title = _('Search')
    description = _('Perform a full-text search on the result set.')

    def filter_queryset(self, request, queryset, view):
        """
        This performs a full-text search on the result set
        Eg: ?search=James Joyce
        """
        search_enabled = getattr(settings, 'WAGTAILAPI_SEARCH_ENABLED', True)

        if self.query_param in request.GET:
            if not search_enabled:
                raise BadRequestError("search is disabled")

            # Searching and filtering by tag at the same time is not supported
            if getattr(queryset, '_filtered_by_tag', False):
                raise BadRequestError("filtering by tag with a search query is not supported")

            search_query = request.GET[self.query_param]
            search_operator = request.GET.get('search_operator', None)
            order_by_relevance = 'order' not in request.GET

            sb = get_search_backend()
            try:
                queryset = sb.search(search_query, queryset, operator=search_operator, order_by_relevance=order_by_relevance)
            except FilterFieldError as e:
                raise BadRequestError("cannot filter by '{}' while searching (field is not indexed)".format(e.field_name))
            except OrderByFieldError as e:
                raise BadRequestError("cannot order by '{}' while searching (field is not indexed)".format(e.field_name))

        return queryset

    def get_schema_fields(self, view):
        assert coreapi is not None, 'coreapi must be installed to use `get_schema_fields()`'
        assert coreschema is not None, 'coreschema must be installed to use `get_schema_fields()`'
        return [
            coreapi.Field(
                name=self.query_param,
                required=False,
                location='query',
                schema=coreschema.String(
                    title=force_text(self.title),
                    description=force_text(self.description)
                )
            )
        ]


class ChildOfFilter(BaseFilterBackend):
    """
    Implements the ?child_of filter used to filter the results to only contain
    pages that are direct children of the specified page.
    """
    query_param = 'child_of'
    title = _('Child of')
    description = _('Filter the results to only contain pages that are '
                    'direct children of the specified page.')

    def get_root_page(self, request):
        return Page.get_first_root_node()

    def get_page_by_id(self, request, page_id):
        return Page.objects.get(id=page_id)

    def filter_queryset(self, request, queryset, view):
        if self.query_param in request.GET:
            try:
                parent_page_id = int(request.GET[self.query_param])
                if parent_page_id < 0:
                    raise ValueError()

                parent_page = self.get_page_by_id(request, parent_page_id)
            except ValueError:
                if request.GET[self.query_param] == 'root':
                    parent_page = self.get_root_page(request)
                else:
                    raise BadRequestError(
                            "{param} must be a positive integer".format(
                                param=self.query_param))
            except Page.DoesNotExist:
                raise BadRequestError("parent page doesn't exist")

            queryset = queryset.child_of(parent_page)
            queryset._filtered_by_child_of = parent_page

        return queryset

    def get_schema_fields(self, view):
        assert coreapi is not None, 'coreapi must be installed to use `get_schema_fields()`'
        assert coreschema is not None, 'coreschema must be installed to use `get_schema_fields()`'
        return [
            coreapi.Field(
                name=self.query_param,
                required=False,
                location='query',
                schema=coreschema.Integer(
                    title=force_text(self.title),
                    description=force_text(self.description)
                )
            )
        ]


class RestrictedChildOfFilter(ChildOfFilter):
    """
    A restricted version of ChildOfFilter that only allows pages in the current
    site to be specified.
    """
    title = _('Restricted child of')
    description = _('Filter the results to only contain pages that are '
                    'direct children of the specified page and are '
                    'part of the current site.')

    def get_root_page(self, request):
        return request.site.root_page

    def get_page_by_id(self, request, page_id):
        site_pages = pages_for_site(request.site)
        return site_pages.get(id=page_id)


class DescendantOfFilter(BaseFilterBackend):
    """
    Implements the ?decendant_of filter which limits the set of pages to a
    particular branch of the page tree.
    """
    query_param = 'descendant_of'
    title = _('Descendant of')
    description = _('Filter which limits the set of pages to a '
                    'particular branch of the page tree.')

    def get_root_page(self, request):
        return Page.get_first_root_node()

    def get_page_by_id(self, request, page_id):
        return Page.objects.get(id=page_id)

    def filter_queryset(self, request, queryset, view):
        if self.query_param in request.GET:
            if hasattr(queryset, '_filtered_by_child_of'):
                raise BadRequestError(
                        "filtering by {param} with child_of is not supported".format(
                            param=self.query_param))
            try:
                parent_page_id = int(request.GET[self.query_param])
                if parent_page_id < 0:
                    raise ValueError()

                parent_page = self.get_page_by_id(request, parent_page_id)
            except ValueError:
                if request.GET[self.query_param] == 'root':
                    parent_page = self.get_root_page(request)
                else:
                    raise BadRequestError(
                            "{param} must be a positive integer".format(
                                param=self.query_param))
            except Page.DoesNotExist:
                raise BadRequestError("ancestor page doesn't exist")

            queryset = queryset.descendant_of(parent_page)

        return queryset

    def get_schema_fields(self, view):
        assert coreapi is not None, 'coreapi must be installed to use `get_schema_fields()`'
        assert coreschema is not None, 'coreschema must be installed to use `get_schema_fields()`'
        return [
            coreapi.Field(
                name=self.query_param,
                required=False,
                location='query',
                schema=coreschema.Integer(
                    title=force_text(self.title),
                    description=force_text(self.description)
                )
            )
        ]


class RestrictedDescendantOfFilter(DescendantOfFilter):
    """
    A restricted version of DecendantOfFilter that only allows pages in the current
    site to be specified.
    """
    title = _('Restricted descendant of')
    description = _('Filter which limits the set of pages to a '
                    'particular branch of the page tree in '
                    'the current site.')

    def get_root_page(self, request):
        return request.site.root_page

    def get_page_by_id(self, request, page_id):
        site_pages = pages_for_site(request.site)
        return site_pages.get(id=page_id)


class ForExplorerFilter(BaseFilterBackend):
    query_param = 'for_explorer'
    title = _('For explorer')
    description = _('')

    def filter_queryset(self, request, queryset, view):
        if request.GET.get('for_explorer'):
            if not hasattr(queryset, '_filtered_by_child_of'):
                raise BadRequestError("filtering by for_explorer without child_of is not supported")

            parent_page = queryset._filtered_by_child_of
            for hook in hooks.get_hooks('construct_explorer_page_queryset'):
                queryset = hook(parent_page, queryset, request)

        return queryset

    def get_schema_fields(self, view):
        assert coreapi is not None, 'coreapi must be installed to use `get_schema_fields()`'
        assert coreschema is not None, 'coreschema must be installed to use `get_schema_fields()`'
        return [
            coreapi.Field(
                name=self.query_param,
                required=False,
                location='query',
                schema=coreschema.String(
                    title=force_text(self.title),
                    description=force_text(self.description)
                )
            )
        ]
