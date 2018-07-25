from django.db import models
from django.test import TestCase
from django.utils.encoding import force_text
from taggit.managers import TaggableManager
import unittest

from rest_framework import generics
from rest_framework.compat import coreapi, coreschema
from wagtail.api.v2 import filters


class FieldsFilterModel(models.Model):
    integer_field = models.IntegerField(primary_key=True)
    charfield = models.CharField(max_length=100)
    boolean_field = models.BooleanField()
    taggable_manager = TaggableManager()


class FieldsFilterTest(TestCase):
    def setUp(self):
        self.filter_backend = filters.FieldsFilter()

    @unittest.skipIf(not coreschema, 'coreschema is not installed')
    def test_get_schema_fields(self):

        class FieldsListView(generics.ListAPIView):
            model = FieldsFilterModel

            @classmethod
            def get_available_fields(cls, *args, **kwargs):
                field_names = [
                    'integer_field', 'charfield', 'boolean_field', 'taggable_manager'
                ]
                fields = [cls.model._meta.get_field(field) for field in field_names]
                return fields

        fields = [
            coreapi.Field(
                name='integer_field',
                required=False,
                location='query',
                schema=coreschema.Integer(
                    title=force_text('Integer Field'),
                    description=force_text('Filter results using an exact match.'),
                ),
            ),
            coreapi.Field(
                name='charfield',
                required=False,
                location='query',
                schema=coreschema.String(
                    title=force_text('Charfield'),
                    description=force_text('Filter results using an exact match.'),
                ),
            ),
            coreapi.Field(
                name='boolean_field',
                required=False,
                location='query',
                schema=coreschema.Boolean(
                    title=force_text('Boolean Field'),
                    description=force_text('Filter results using an exact match.'),
                ),
            ),
            coreapi.Field(
                name='taggable_manager',
                required=False,
                location='query',
                schema=coreschema.String(
                    title=force_text('Taggable Manager'),
                    description=force_text(
                        'Filter results using a comma-separated list of tags.'
                    ),
                ),
            ),
        ]
        self.assertEqual(self.filter_backend.get_schema_fields(FieldsListView), fields)
