import json

from ninja import ModelSchema

from .models import *


class SearchEndpoint(ModelSchema):
    class Meta:
        model = SearchEndpoints
        fields = "__all__"


class Team(ModelSchema):
    class Meta:
        model = Teams
        fields = "__all__"


class Scorer(ModelSchema):
    class Meta:
        model = Scorers
        fields = "__all__"


class Case(ModelSchema):
    class Meta:
        model = Cases
        fields = "__all__"


def _as_dict(raw):
    """Read a column that holds JSON, whether or not the driver parsed it.

    ``queries.options`` and ``query_doc_pairs.options`` are MySQL json columns
    and arrive as dicts; ``query_doc_pairs.document_fields`` is TEXT holding a
    JSON string and arrives as text. Both end up here.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw  # in case options is already JSONField / dict
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


class Query(ModelSchema):
    query_options: dict

    class Meta:
        model = Queries
        fields = "__all__"
        exclude = ['options', ]

    @staticmethod
    def resolve_query_options(obj):
        return _as_dict(getattr(obj, "options", None))


class QueryDocPair(ModelSchema):
    """One judgeable query/document pair -- what a book is actually made of.

    ``Book#queries_count`` is ``query_doc_pairs.select(:query_text).distinct``,
    so a book's queries are the distinct query_texts here; there is no separate
    row for a query. Note this is not ``Queries``: that table belongs to a case.
    """
    query_options: dict
    document_fields: dict

    class Meta:
        model = QueryDocPairs
        fields = "__all__"
        exclude = ['options', 'document_fields', ]

    @staticmethod
    def resolve_query_options(obj):
        return _as_dict(getattr(obj, "options", None))

    @staticmethod
    def resolve_document_fields(obj):
        return _as_dict(getattr(obj, "document_fields", None))


class Rating(ModelSchema):
    class Meta:
        model = Ratings
        fields = "__all__"


class Book(ModelSchema):
    class Meta:
        model = Books
        fields = "__all__"
