"""MCP collections over the Quepid schema (see docs/mcp-server-plan.md).

Read-only. Every collection is scoped to the API token's owner and the teams
they belong to; Quepid administrators see everything.

Two schema traits drive most of the code here:

* Nothing routes to the default database. `QuepidScoped.get_queryset` pins
  `.using('quepid')` once, and every scoping subquery below repeats it so the
  whole filter stays inside one connection as real SQL.
* The habtm join tables `teams_books` and `teams_search_endpoints` have no
  primary key of their own, so Django invents an `id` AutoField that does not
  exist in Rails' schema. Selecting one would raise. Every query against them
  therefore ends in `.values(...)`, which pins the SELECT list to real columns.

`extra_instructions` is prompt text, not documentation: it is the client's only
source for anything the generated JSON schema cannot express -- which of the
`*_id` columns are real references, how tinyint booleans behave, and which
fields are too large to select casually.

SECURITY -- `fields` IS NOT AN ACCESS CONTROL. django-mcp-server uses it only to
generate the advertised JSON schema (`query_tool.py:660`) and to pick text
search fields; it never touches the queryset. The pipeline ends at
`queryset.values()` with no arguments (`query_tool.py:323`), which selects every
column on the model, and `$match` field names are passed to `filter()` without
validation. So every column of every published model is readable regardless of
what `fields` says. Publishing a model here exposes the whole row.

That is why `Users` is not published: it holds password hashes and reset
tokens, and the ninja REST API does not expose it either (no schema in
quepid/schemas.py, no router in api/). The models that ARE published expose
exactly what the REST API already hands to the same token via
`fields = "__all__"` -- notably SearchEndpoints, whose credential columns are
already returned by GET /api/search_endpoints/.
"""
import logging

from django.db.models import Q
from mcp_server import ModelQueryToolset

import quepid.models as qmodels
from quepid_mcp.auth import QuepidPrincipal

logger = logging.getLogger(__name__)

# Repeated verbatim wherever a column looks like a foreign key and is not one.
RAW_ID_WARNING = (
    'is a raw integer, NOT a reference -- $lookup cannot traverse it. '
    'Resolve it with a separate query against the {collection} collection '
    'using $match {{"id": <value>}}.'
)

LOOKUP_FIELD_NOTE = (
    'In $lookup and $match use the field name "{field}"; results show it as '
    '"{field}_id", which does NOT work as a localField.'
)


def _team_ids(user):
    """Teams the user belongs to."""
    return qmodels.TeamsMembers.objects \
        .using('quepid') \
        .filter(member_id=user.id) \
        .values('team_id')


def _visible_case_ids(user):
    """Cases the user owns, plus cases shared with any of their teams."""
    shared = qmodels.TeamsCases.objects \
        .using('quepid') \
        .filter(team_id__in=_team_ids(user)) \
        .values('case_id')

    return qmodels.Cases.objects \
        .using('quepid') \
        .filter(Q(owner_id=user.id) | Q(id__in=shared)) \
        .values('id')


def _visible_book_ids(user):
    """Books the user owns, plus books shared with any of their teams."""
    shared = qmodels.TeamsBooks.objects \
        .using('quepid') \
        .filter(team_id__in=_team_ids(user)) \
        .values('book_id')

    return qmodels.Books.objects \
        .using('quepid') \
        .filter(Q(owner_id=user.id) | Q(id__in=shared)) \
        .values('id')


class QuepidScoped:
    """Mixin for every published collection: right database, right rows.

    Subclasses implement `scope()` rather than `get_queryset()` so the alias
    and the fail-closed checks cannot be forgotten.

    Deliberately NOT a ModelQueryToolset subclass. ModelQueryToolsetMeta
    registers every subclass by name as a collection, so an intermediate base
    would be published with `model = None` and crash autodiscovery. A plain
    mixin is built by `type`, so the metaclass never sees it.
    """

    def get_queryset(self):
        queryset = self.model._default_manager \
            .using('quepid') \
            .all()

        user = getattr(self.request, 'user', None)

        # IsAuthenticated should have rejected an unauthenticated call long
        # before this, so reaching here means something is misconfigured --
        # return nothing rather than everything.
        if not isinstance(user, QuepidPrincipal):
            logger.warning('MCP query without a Quepid user; returning no rows.')
            return queryset.none()

        if user.administrator:
            return queryset

        return self.scope(queryset, user)

    def scope(self, queryset, user):
        raise NotImplementedError


class CasesToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.Cases
    fields = [
        'id', 'case_name', 'last_try_number', 'owner', 'archived',
        'scorer_id', 'book_id', 'public', 'nightly',
        'created_at', 'updated_at',
    ]
    extra_instructions = (
        'A case is a Quepid relevance-testing workspace: a named set of search '
        'queries evaluated against a search endpoint. Its queries are in the '
        '"queries" collection ($match {"case": <id>}) and the judgements on '
        'those queries are in "ratings".\n\n'
        'WARNING: "scorer_id" ' + RAW_ID_WARNING.format(collection='scorers') + ' '
        'WARNING: "book_id" ' + RAW_ID_WARNING.format(collection='books') + '\n\n'
        '"owner_id" identifies the owning user. There is no users collection '
        'in this server, so it cannot be resolved to a name -- report it as an '
        'id, or get the name from Quepid itself.\n\n'
        '"archived", "public" and "nightly" are MySQL tinyints: 1, 0 or null. '
        'null is NOT the same as 0 -- an unset flag reads as null. '
        '"last_try_number" counts the query-tuning iterations run on the case. '
        'Latest = highest id, or sort by created_at descending.'
    )

    def scope(self, queryset, user):
        return queryset.filter(id__in=_visible_case_ids(user))


class QueriesToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.Queries
    fields = [
        'id', 'query_text', 'information_need', 'notes', 'case',
        'created_at', 'updated_at',
    ]
    extra_instructions = (
        'A query is one search string being evaluated inside a case. '
        '"query_text" is the string sent to the search engine; '
        '"information_need" is the human description of what the searcher '
        'actually wanted, and is often null.\n\n'
        '"case" is a real reference to the "cases" collection. '
        + LOOKUP_FIELD_NOTE.format(field='case') + '\n\n'
        'The relevance judgements for a query are in the "ratings" collection '
        '($match {"query": <id>}). The per-query search options column is '
        'deliberately not published. Latest = highest id.'
    )

    def scope(self, queryset, user):
        return queryset.filter(case_id__in=_visible_case_ids(user))


class RatingsToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.Ratings
    fields = [
        'id', 'doc_id', 'rating', 'query', 'user_id',
        'created_at', 'updated_at',
    ]
    extra_instructions = (
        'A rating is one person\'s relevance judgement of one document for one '
        'query, on the CASE side of Quepid. This is NOT the "judgements" '
        'collection, which is the book-side equivalent -- do not mix them.\n\n'
        '"query" is a real reference to the "queries" collection. '
        + LOOKUP_FIELD_NOTE.format(field='query') + '\n\n'
        'WARNING: "user_id" ' + RAW_ID_WARNING.format(collection='users') + '\n\n'
        '"doc_id" is the search engine\'s own document identifier, a string, '
        'not a row id in this database. "rating" is a float on the scale of '
        'whichever scorer the case uses (commonly 0-3 or 0-10) -- there is no '
        'fixed range, so compare ratings only within one case.'
    )

    def scope(self, queryset, user):
        return queryset.filter(query__case_id__in=_visible_case_ids(user))


class BooksToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.Books
    fields = [
        'id', 'name', 'owner_id', 'archived',
        'scale', 'scale_with_labels', 'scoring_guidelines',
        'support_implicit_judgements', 'show_rank',
        'created_at', 'updated_at',
    ]
    extra_instructions = (
        'A book is a reusable corpus of query/document judgements that can be '
        'shared across cases. Its query/document pairs are in the '
        '"querydocpairs" collection ($match {"book": <id>}) and the verdicts '
        'on those pairs are in "judgements".\n\n'
        '"scale" and "scale_with_labels" define the rating scale the book is '
        'judged on; they replaced the scorer and selection-strategy references '
        'books carried before Quepid v8.4.0.\n\n'
        '"owner_id" identifies the owning user and cannot be resolved to a '
        'name -- there is no users collection in this server.\n\n'
        '"support_implicit_judgements", "show_rank" and "archived" are MySQL '
        'tinyints: 1, 0 or null, where null is not the same as 0. '
        'Latest = highest id.'
    )

    def scope(self, queryset, user):
        return queryset.filter(id__in=_visible_book_ids(user))


class QueryDocPairsToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.QueryDocPairs
    fields = [
        'id', 'query_text', 'doc_id', 'position', 'information_need',
        'notes', 'document_fields', 'book', 'created_at', 'updated_at',
    ]
    extra_instructions = (
        'A query/document pair is one candidate document for one query inside '
        'a book -- the unit a human actually judges. The verdicts are in the '
        '"judgements" collection ($match {"query_doc_pair": <id>}).\n\n'
        '"book" is a real reference to the "books" collection. '
        + LOOKUP_FIELD_NOTE.format(field='book') + '\n\n'
        'PERFORMANCE: "document_fields" holds the indexed document content as '
        'a JSON text blob and is frequently several kilobytes per row. Use '
        '$project to exclude it unless the question genuinely needs document '
        'content, otherwise a broad query returns megabytes.\n\n'
        '"position" is the rank the document appeared at when the pair was '
        'captured. "doc_id" is the search engine\'s document identifier, a '
        'string, not a row id in this database.'
    )

    def scope(self, queryset, user):
        return queryset.filter(book_id__in=_visible_book_ids(user))


class JudgementsToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.Judgements
    fields = [
        'id', 'rating', 'unrateable', 'judge_later', 'explanation',
        'query_doc_pair', 'user', 'created_at', 'updated_at',
    ]
    extra_instructions = (
        'A judgement is one rater\'s verdict on one query/document pair, on the '
        'BOOK side of Quepid. This is NOT the "ratings" collection, which is '
        'the case-side equivalent -- do not mix them.\n\n'
        '"query_doc_pair" is a real reference to the "querydocpairs" '
        'collection. ' + LOOKUP_FIELD_NOTE.format(field='query_doc_pair') + '\n\n'
        '"user" identifies the rater. There is no users collection in this '
        'server, so it cannot be resolved to a name -- report it as an id, or '
        'get the name from Quepid itself.\n\n'
        '"rating" is a float on the book scorer\'s scale, null when the pair '
        'was skipped. "unrateable" and "judge_later" are MySQL tinyints (1, 0 '
        'or null) marking pairs the rater could not judge or deferred; null '
        'means the flag was never set, which is NOT the same as 0. '
        '"explanation" is free text and often null.'
    )

    def scope(self, queryset, user):
        return queryset.filter(query_doc_pair__book_id__in=_visible_book_ids(user))


# NOTE: there is deliberately no Users collection -- see the SECURITY note in
# the module docstring. `user_id` / `owner_id` columns elsewhere are therefore
# terminal: they identify a person but cannot be resolved to a name here.


class TeamsToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.Teams
    fields = ['id', 'name', 'created_at', 'updated_at']
    extra_instructions = (
        'Teams you belong to. A team is how Quepid shares cases, books, '
        'scorers and search endpoints between users.\n\n'
        'The membership and sharing junction tables are not published, so team '
        'membership cannot be traversed with $lookup. You rarely need to: '
        'every collection in this server is already filtered to what your '
        'teams can see, so this collection mostly answers "which teams am I '
        'in". Latest = highest id.'
    )

    def scope(self, queryset, user):
        return queryset.filter(id__in=_team_ids(user))


class ScorersToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.Scorers
    fields = [
        'id', 'name', 'scale', 'communal', 'owner_id',
        'show_scale_labels', 'created_at', 'updated_at',
    ]
    extra_instructions = (
        'A scorer is the metric a case is graded with (nDCG@10, AP@10, '
        'a custom expression, ...). "communal" is a tinyint marking Quepid\'s '
        'built-in scorers, which everyone can see; your own and your teams\' '
        'scorers appear alongside them.\n\n'
        'This collection is what "cases.scorer_id" points '
        'at, but that is a raw integer, not a reference -- resolve it with '
        '$match {"id": <value>}. "scale" describes the allowed rating values. '
        'The scorer source code is not useful to query and is large.'
    )

    def scope(self, queryset, user):
        shared = qmodels.TeamsScorers.objects \
            .using('quepid') \
            .filter(team_id__in=_team_ids(user)) \
            .values('scorer_id')

        return queryset.filter(
            Q(owner_id=user.id) | Q(communal=1) | Q(id__in=shared)
        )


class SearchEndpointsToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.SearchEndpoints
    fields = [
        'id', 'name', 'search_engine', 'endpoint_url', 'api_method',
        'archived', 'proxy_requests', 'created_at', 'updated_at',
    ]
    extra_instructions = (
        'A search endpoint is the search engine a case queries: its URL, '
        'engine type ("solr", "es", "os", "vectara", ...) and HTTP method. '
        'Cases reach it through the "tries" collection, not directly.\n\n'
        'SENSITIVE: rows carry credential columns (basic auth, custom headers, '
        'mapper code). They are not in the advertised schema and you should '
        'not select or report them; $project only the fields you need. This is '
        'the same exposure as the REST API\'s GET /api/search_endpoints/.\n\n'
        '"archived" and "proxy_requests" are tinyints (1, 0 or null). '
        '"owner_id" identifies the owning user and cannot be resolved to a '
        'name -- there is no users collection in this server.'
    )

    def scope(self, queryset, user):
        shared = qmodels.TeamsSearchEndpoints.objects \
            .using('quepid') \
            .filter(team_id__in=_team_ids(user)) \
            .values('search_endpoint_id')

        return queryset.filter(Q(owner_id=user.id) | Q(id__in=shared))


class TriesToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.Tries
    fields = [
        'id', 'try_number', 'name', 'case', 'search_endpoint', 'field_spec',
        'number_of_rows', 'escape_query', 'created_at', 'updated_at',
    ]
    extra_instructions = (
        'A try is one tuning iteration of a case: a specific set of query '
        'parameters run against a search endpoint. "cases.last_try_number" '
        'names the newest one, and "try_number" is unique within a case -- so '
        '"the current try" is the highest try_number for that case, NOT the '
        'highest id across the table.\n\n'
        '"case" and "search_endpoint" are real references. '
        + LOOKUP_FIELD_NOTE.format(field='case') + '\n\n'
        '"field_spec" maps search result fields to Quepid display fields. '
        '"escape_query" is a tinyint. The raw query parameter template is a '
        'very large text column -- do not select it unless asked for it.'
    )

    def scope(self, queryset, user):
        return queryset.filter(case_id__in=_visible_case_ids(user))


class SnapshotsToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.Snapshots
    fields = ['id', 'name', 'case', 'try_id', 'scorer_id',
              'created_at', 'updated_at']
    extra_instructions = (
        'A snapshot freezes the search results for every query in a case at a '
        'point in time, so runs can be compared. "case" is a real reference.\n\n'
        'WARNING: "try_id" ' + RAW_ID_WARNING.format(collection='tries') + ' '
        'WARNING: "scorer_id" ' + RAW_ID_WARNING.format(collection='scorers') + '\n\n'
        'The per-query scores within a snapshot are in the "snapshotqueries" '
        'collection ($match {"snapshot": <id>}).'
    )

    def scope(self, queryset, user):
        return queryset.filter(case_id__in=_visible_case_ids(user))


class SnapshotQueriesToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.SnapshotQueries
    fields = ['id', 'query', 'snapshot', 'score', 'all_rated',
              'number_of_results', 'response_status']
    extra_instructions = (
        'One query\'s outcome inside a snapshot: its score, how many results '
        'came back, and the HTTP status of the search request. This is where '
        'to look for "how did case X score over time" -- join snapshots to '
        'their case, then compare scores here.\n\n'
        '"query" and "snapshot" are real references. '
        + LOOKUP_FIELD_NOTE.format(field='snapshot') + '\n\n'
        '"score" is null when the query was never scored. "all_rated" is a '
        'tinyint (1, 0 or null) meaning every returned document had a rating. '
        '"response_status" is an HTTP status; non-200 means the search failed '
        'and the score is meaningless. There are no timestamps here -- order '
        'by the parent snapshot\'s created_at.'
    )

    def scope(self, queryset, user):
        return queryset.filter(snapshot__case_id__in=_visible_case_ids(user))


class TeamsCasesToolset(QuepidScoped, ModelQueryToolset):
    model = qmodels.TeamsCases
    fields = ['case', 'team']
    extra_instructions = (
        'Which cases are shared with which teams. Both "case" and "team" are '
        'real references, so this is the way to answer "who else can see this '
        'case".\n\n'
        'CAUTION: the underlying table has a composite primary key (case_id, '
        'team_id) that Django cannot express, so the schema shows "case" as '
        'the primary key. Case ids are NOT unique in this collection -- a case '
        'shared with three teams appears three times. Do not treat a row as '
        'one case.'
    )

    def scope(self, queryset, user):
        return queryset.filter(team_id__in=_team_ids(user))
