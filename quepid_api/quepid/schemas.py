import json

from typing import List

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


def _as_scale(raw):
    """Read ``books.scale``, which is a varchar of comma-joined integers.

    The Rails side of this is ``ScaleSerializer``: dump joins on a comma, load
    splits, casts with ``Integer()`` and sorts. Sorting on the way out is part
    of the contract, not tidiness -- ``JudgementHelper#generate_rating_buttons``
    walks the scale in order to lay the rating buttons out.
    """
    if not raw:
        return []
    if isinstance(raw, list):
        return sorted(raw)
    return sorted(int(part) for part in str(raw).split(',') if part.strip())


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


class Judgement(ModelSchema):
    """One rater's verdict on one query/doc pair.

    Book-level, and not to be confused with ``Rating``: a rating hangs off a
    *case* query and is what a scorer reads, while a judgement hangs off a
    book's pair. Up to three judgements exist per pair, one per rater --
    ``SelectionStrategy`` offers a rater only pairs nobody-but-them has yet to
    rate -- so a human's label and an AI judge's sit side by side here.
    """

    class Meta:
        model = Judgements
        fields = "__all__"


class Rating(ModelSchema):
    class Meta:
        model = Ratings
        fields = "__all__"


class Book(ModelSchema):
    #: The ratings a judge may give in this book, ascending. Stored as the
    #: varchar "0,1,2,3"; rendered as a list, so it round-trips with CreateBook.
    scale: List[int]
    #: What each of those ratings means, e.g. {"0": "Irrelevant", "3": "Exact"}.
    #: Keys are strings: Rails looks them up with ``dig(score.to_s)``.
    scale_with_labels: dict

    class Meta:
        model = Books
        fields = "__all__"
        exclude = ['scale', 'scale_with_labels', ]

    @staticmethod
    def resolve_scale(obj):
        return _as_scale(getattr(obj, "scale", None))

    @staticmethod
    def resolve_scale_with_labels(obj):
        return _as_dict(getattr(obj, "scale_with_labels", None))


class AiJudge(ModelSchema):
    """An LLM judge -- which is a ``users`` row, not a table of its own.

    Quepid's ``User.only_ai_judges`` scope is ``where.not(llm_key: nil)`` and
    its ``ai_judge?`` predicate is the same test, so a non-null ``llm_key`` is
    the whole of what makes a user a judge.

    The fields are listed rather than ``"__all__"`` because this is the login
    table: ``email``, ``password``, ``administrator`` and the invitation
    columns have no place in a judge response. ``llm_key`` is left out too --
    it is a paid LLM credential, which Rails encrypts at rest, so this API
    accepts it and never hands it back.
    """
    #: Which model to ask, and how. Rails keeps this inside the ``options``
    #: JSON under a ``judge_options`` key rather than in a column of its own,
    #: behind an accessor pair whose own comment reads "ugh, why isn't this
    #: :judge_options?". Flattened here, so callers need not know that.
    judge_options: dict

    class Meta:
        model = Users
        fields = ['id', 'name', 'system_prompt', 'created_at', 'updated_at']

    @staticmethod
    def resolve_judge_options(obj):
        return _as_dict(getattr(obj, "options", None)).get('judge_options', {})
