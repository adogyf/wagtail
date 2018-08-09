from django.db import models
from django.test import TestCase
from django.utils.encoding import force_text
from taggit.managers import TaggableManager
import unittest

from rest_framework import generics
from rest_framework.compat import coreapi, coreschema
from wagtail.api.v2 import filters


class FieldsFilterModel(models.Model):
    taggable_manager = TaggableManager()
    integer_field = models.IntegerField(primary_key=True)
    char_field = models.CharField(max_length=100)
    boolean_field = models.BooleanField()


class FieldsFilterTest(TestCase):
    def setUp(self):
        self.filter_backend = filters.FieldsFilter()
        self.maxDiff = None

    @unittest.skipIf(not coreschema, 'coreschema is not installed')
    def test_get_schema_fields(self):

        class FieldsListView(generics.ListAPIView):
            model = FieldsFilterModel

            @classmethod
            def get_available_fields(cls, *args, **kwargs):
                field_names = [
                    'taggable_manager', 'integer_field', 'char_field', 'boolean_field'
                ]
                return field_names

        fields = [
            coreapi.Field(
                name='taggable_manager',
                required=False,
                location='query',
                schema=coreschema.String(
                    title=force_text('taggable_manager'),
                    description=force_text(
                        'Filter results using a comma-separated list of tags.'
                    ),
                ),
            ),
            coreapi.Field(
                name='integer_field',
                required=False,
                location='query',
                schema=coreschema.Integer(
                    title=force_text('integer_field'),
                    description=force_text('Filter results using an exact match.'),
                ),
            ),
            coreapi.Field(
                name='char_field',
                required=False,
                location='query',
                schema=coreschema.String(
                    title=force_text('char_field'),
                    description=force_text('Filter results using an exact match.'),
                ),
            ),
            coreapi.Field(
                name='boolean_field',
                required=False,
                location='query',
                schema=coreschema.Boolean(
                    title=force_text('boolean_field'),
                    description=force_text('Filter results using an exact match.'),
                ),
            ),
        ]
        self.assertEqual(self.filter_backend.get_schema_fields(FieldsListView), fields)
