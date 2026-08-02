"""The MCP server's global instructions.

Delivered to the client once, up front, and its only map of the data model --
so a vague line here produces confidently wrong queries. Per-collection detail
belongs in each toolset's ``extra_instructions`` in mcp.py; keep this to the
map and the traps that span collections.

Lives in the app rather than in settings.py so the prose sits next to the
toolsets it describes. Imported by settings, so this module must stay free of
Django imports -- it runs before the app registry is ready.
"""

SERVER_INSTRUCTIONS = (
    'Quepid exposes read-only query access to a Quepid search-relevance '
    'testing database.\n\n'

    'Collections: "cases" (relevance-testing workspaces), "queries" '
    '(search strings inside a case), "ratings" (per-document judgements '
    'inside a case), "books" (reusable judgement corpora), '
    '"querydocpairs" (query/document pairs inside a book), "judgements" '
    '(verdicts on those pairs), "tries" (tuning iterations of a case), '
    '"snapshots" and "snapshotqueries" (frozen results and their scores), '
    '"searchendpoints" (the search engines cases query), "scorers" (the '
    'metrics used to grade), "teams" and "teamscases" (sharing).\n\n'

    'There is no users collection: user accounts are not exposed. Columns '
    'named owner_id or user_id identify a person but cannot be resolved to '
    'a name here -- report them as ids.\n\n'

    'Quepid has two parallel judgement worlds and they are easy to '
    'confuse: a CASE holds queries and ratings; a BOOK holds querydocpairs '
    'and judgements. A case may draw on a book, but ratings and judgements '
    'are different tables with different scales. Never mix them in one '
    'answer without saying which side you used.\n\n'

    'References, traversable with $lookup: queries.case -> cases, '
    'ratings.query -> queries, querydocpairs.book -> books, '
    'judgements.query_doc_pair -> querydocpairs, tries.case -> cases, '
    'tries.search_endpoint -> searchendpoints, snapshots.case -> cases, '
    'snapshotqueries.snapshot -> snapshots, snapshotqueries.query -> '
    'queries, teamscases.case -> cases, teamscases.team -> teams. '
    'Resolve these in one query with $lookup rather than returning raw ids '
    'the user cannot read. localField must be the field name ("case", '
    '"query", "book", "owner"); results display the "_id" form '
    '("case_id"), which does NOT work as a localField.\n\n'

    'These columns look like references and are NOT -- $lookup cannot '
    'traverse them: cases.scorer_id, cases.book_id, books.owner_id, '
    'ratings.user_id, judgements.user_id, '
    'snapshots.try_id, snapshots.scorer_id, scorers.owner_id. Query the '
    'target collection separately with $match {"id": <value>}.\n\n'

    'Rows may carry columns beyond the advertised schema, including '
    'credentials on searchendpoints. Select only the fields you need with '
    '$project, and never report a credential column.\n\n'

    '"Latest" means highest id, or sort by created_at / updated_at '
    'descending. Fields that look boolean (archived, public, nightly, '
    'administrator, locked, unrateable, judge_later) are MySQL tinyints: '
    '1, 0 or null, and null is NOT false -- it means never set.\n\n'

    'Every result is already scoped to the API token owner and the teams '
    'they belong to. An empty result means the data is not shared with '
    'you, not that it does not exist -- say so rather than reporting that '
    'a case or book is missing.'
)
