"""Integration tests for the MCP server at ``/mcp/mcp``.

The REST suite never touches this surface, yet it is the one an AI assistant
actually talks to. These tests are modelled on the demo linked from
``README.md`` ("Quepid MCP"), which drives the server from Claude Code with
three prompts:

1. *"what cases do i have"* -- list cases with their try counts, nightly flags
   and books, separating archived ones and ones owned by somebody else.
2. *"show me 5 queries in case lexical"* -- resolve a case **by name**, then
   page its queries.
3. *"show me a query for that case. but only query. dont show url of server"* --
   pull the query DSL off the case's latest try, without leaking the endpoint.

Each prompt is one class below. What the assistant renders is its own business;
what this suite pins down is the data it had to fetch to render it, because
that is what the upgrade can break.

Everything is driven through the deployed stack over HTTP, and every row these
tests assert on is created by their own fixtures -- the seeded demo database is
never assumed to contain anything in particular.
"""
import pytest
import requests

from conftest import BASE_URL, MCP_URL, TARGET, _create, _discard, unique
from mcp_client import McpError


pytestmark = pytest.mark.integration


#: A recognisable Elasticsearch query DSL. ``create_case`` stores whatever
#: string it is given as ``tries.query_params`` (``api/cases.py:101``), which is
#: exactly what use case 3 reads back.
QUERY_DSL = (
    '{"query": {"bool": {"should": ['
    '{"match": {"name": {"query": "#$query##", "boost": 10}}}, '
    '{"prefix": {"brand.raw": {"value": "#$query##", "boost": 2}}}'
    '], "minimum_should_match": 1}}}'
)


@pytest.fixture(scope="module")
def demo(api, request):
    """A case shaped like the one in the video, with a DSL and two queries.

    Module-scoped: every test here reads the same rows and none mutate them, so
    building this once keeps the suite fast. Teardown archives the case (DELETE
    is a soft delete -- see ``api/cases.py:delete_case``) and removes the rest.
    """
    scorer = _create(api, f"{BASE_URL}/scorers/", {"name": unique("mcp-scorer")})
    endpoint = _create(api, f"{BASE_URL}/search_endpoints/", {
        "name": unique("mcp-endpoint"),
        "endpoint_url": "http://search.invalid/solr/collection1/select",
        "search_engine": "solr",
        "api_method": "GET",
    })
    case = _create(api, f"{BASE_URL}/case/", {
        "name": unique("mcp-case"),
        "scorer_id": scorer["id"],
        "search_endpoint_id": endpoint["id"],
        "search_query": QUERY_DSL,
        "nightly": 0,
    })
    queries = [
        _create(api, f"{BASE_URL}/query/{case['id']}/", {
            "query_text": text,
            "query_options": {"fq": "in_stock:true", "rows": 20},
        })
        for text in ("bruine schoenen", "nintendo switch controller")
    ]

    yield {"scorer": scorer, "endpoint": endpoint, "case": case, "queries": queries}

    for query in queries:
        _discard(api, f"{BASE_URL}/query/{case['id']}/{query['id']}")
    _discard(api, f"{BASE_URL}/case/{case['id']}/")
    _discard(api, f"{BASE_URL}/search_endpoints/{endpoint['id']}/")
    _discard(api, f"{BASE_URL}/scorers/{scorer['id']}/")


def _ids(rows):
    return {row["id"] for row in rows}


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class TestProtocol:
    """The handshake and tool surface the client library depends on."""

    def test_initialize_reports_a_server(self, mcp):
        result = mcp.initialize()
        assert result["serverInfo"]["name"]
        assert result["protocolVersion"]

    def test_publishes_exactly_two_tools(self, mcp):
        """Collections are a *parameter*, not a tool each.

        Worth pinning: it is the single most surprising thing about this
        server, and a client written against a tool-per-collection API would
        silently find nothing to call.
        """
        assert sorted(mcp.tool_names()) == [
            "get_server_instructions",
            "query_data_collections",
        ]

    def test_server_instructions_describe_the_collections(self, mcp):
        text = mcp.instructions()
        assert "cases" in text and "queries" in text
        assert "no users collection" in text.lower()

    def test_requires_authentication(self, live_stack):
        """Auth is DRF's IsAuthenticated over the same bearer tokens."""
        response = requests.post(
            MCP_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "anon", "version": "1"}}},
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
            timeout=10,
        )
        assert response.status_code in (401, 403), response.text[:300]

    def test_unpublished_collection_is_rejected(self, mcp):
        """A model with no toolset is not queryable, however plausible the name."""
        with pytest.raises(McpError):
            mcp.query("users", [{"$limit": 1}])


# ---------------------------------------------------------------------------
# Use case 1 -- "what cases do i have"
# ---------------------------------------------------------------------------

class TestListMyCases:
    """The case listing, including every column the video's table shows."""

    def test_my_case_is_listed(self, mcp, demo):
        rows = mcp.query("cases", [{"$match": {"id": demo["case"]["id"]}}])
        assert len(rows) == 1
        assert rows[0]["case_name"] == demo["case"]["case_name"]

    def test_case_row_carries_the_listing_columns(self, mcp, demo):
        """id, name, try count anchor, book, nightly and archived.

        The video renders a table of exactly these; if any stops coming back
        the assistant silently drops a column instead of failing.
        """
        row = mcp.query("cases", [{"$match": {"id": demo["case"]["id"]}}])[0]
        assert {
            "id", "case_name", "last_try_number", "archived",
            "nightly", "book_id", "owner_id", "updated_at",
        } <= set(row)

    def test_active_and_archived_cases_can_be_separated(self, mcp, demo):
        """The video splits the list into active and "Archived (owner 2)".

        ``cases.archived`` is a nullable tinyint, so "active" is *not* ``0`` --
        a case Quepid wrote itself can be NULL. The REST layer excludes 1 for
        the same reason (see the CHANGELOG entry for ``GET /api/case/``).
        """
        case_id = demo["case"]["id"]

        active = mcp.query("cases", [{"$match": {"id": case_id, "archived": 0}}])
        assert _ids(active) == {case_id}

        archived = mcp.query("cases", [{"$match": {"id": case_id, "archived": 1}}])
        assert archived == []

    def test_cases_can_be_sorted_by_recency(self, mcp, demo):
        """"...the ones that updated most recently" needs a working $sort."""
        rows = mcp.query("cases", [{"$sort": {"updated_at": -1}}, {"$limit": 5}])
        assert rows, "no cases visible at all"
        stamps = [r["updated_at"] for r in rows if r.get("updated_at")]
        assert stamps == sorted(stamps, reverse=True)

    def test_try_count_per_case(self, mcp, demo):
        """The "tries" column: tries belong to a case and are counted per case.

        ``create_case`` writes exactly one try alongside the case, so a freshly
        created case has one -- a fixed number this test can assert on.
        """
        rows = mcp.query("tries", [{"$match": {"case": demo["case"]["id"]}}])
        assert len(rows) == 1

    def test_nightly_cases_can_be_singled_out(self, mcp, demo):
        """"four cases run nightly (3, 8, 19, 27)" -- the fixture sets 0."""
        row = mcp.query("cases", [{"$match": {"id": demo["case"]["id"]}}])[0]
        assert row["nightly"] in (0, 1, None)
        assert row["nightly"] != 1


# ---------------------------------------------------------------------------
# Use case 2 -- "show me 5 queries in case lexical"
# ---------------------------------------------------------------------------

class TestQueriesInANamedCase:
    """Resolving a case by name, then paging its queries."""

    def test_case_can_be_resolved_by_name(self, mcp, demo):
        """The prompt names the case; the id has to be looked up from it."""
        rows = mcp.query("cases", [
            {"$match": {"case_name": demo["case"]["case_name"]}},
        ])
        assert _ids(rows) == {demo["case"]["id"]}

    def test_queries_are_scoped_to_their_case(self, mcp, demo):
        rows = mcp.query("queries", [{"$match": {"case": demo["case"]["id"]}}])
        assert _ids(rows) == _ids(demo["queries"])

    def test_queries_can_be_limited(self, mcp, demo):
        """"show me **5**" -- $limit is what keeps the answer readable."""
        rows = mcp.query("queries", [
            {"$match": {"case": demo["case"]["id"]}},
            {"$limit": 1},
        ])
        assert len(rows) == 1

    def test_query_rows_carry_text_notes_and_information_need(self, mcp, demo):
        """The video reports "None have notes or an information need set".

        It can only say that because both columns come back.
        """
        row = mcp.query("queries", [{"$match": {"case": demo["case"]["id"]}}])[0]
        assert {"id", "query_text", "notes", "information_need"} <= set(row)
        assert row["query_text"] in {q["query_text"] for q in demo["queries"]}

    def test_query_options_is_an_object_not_a_double_encoded_string(self, mcp, demo):
        """Closes the gap the REST suite provably cannot cover.

        ``queries.options`` is a MySQL json column reflected as a JSONField.
        When ``api/queries.py`` still called ``json.dumps`` on it the column
        held a JSON *string*, and ``resolve_query_options`` hid that from REST
        by falling back to ``json.loads``. MCP returns ``queryset.values()``
        with no resolver in front of it, so this is the only surface in the
        suite where the difference is observable.
        """
        row = mcp.query("queries", [
            {"$match": {"id": demo["queries"][0]["id"]}},
        ])[0]
        assert isinstance(row["options"], dict), (
            f"options came back as {type(row['options']).__name__} -- "
            "api/queries.py is double-encoding it again"
        )
        assert row["options"] == {"fq": "in_stock:true", "rows": 20}


# ---------------------------------------------------------------------------
# Use case 3 -- "show me a query for that case. but only query.
#                dont show url of server"
# ---------------------------------------------------------------------------

class TestQueryDslFromLatestTry:
    """The tuning DSL lives on a try, not on the case or the query."""

    def test_latest_try_exposes_the_query_dsl(self, mcp, demo):
        rows = mcp.query("tries", [
            {"$match": {"case": demo["case"]["id"]}},
            {"$sort": {"try_number": -1}},
            {"$limit": 1},
        ])
        assert len(rows) == 1
        assert rows[0]["query_params"] == QUERY_DSL

    def test_try_is_linked_to_its_case_and_endpoint(self, mcp, demo):
        row = mcp.query("tries", [{"$match": {"case": demo["case"]["id"]}}])[0]
        assert row["case_id"] == demo["case"]["id"]
        assert row["search_endpoint_id"] == demo["endpoint"]["id"]

    def test_endpoint_is_reachable_through_the_try_relation(self, mcp, demo):
        """``Tries.search_endpoint`` is a real FK and must stay one.

        It is not a database constraint, so ``inspectdb`` emits a plain
        ``BigIntegerField`` and every regeneration drops the ForeignKey unless
        it is re-applied by hand (CLAUDE.md, "three documented exceptions").
        A ``$match`` *through* the relation only compiles against a real
        Django FK, which makes this the cheapest guard against that revert.

        Note that ``$lookup`` alone does not embed anything -- in
        django-mcp-server 0.5.7 it registers an alias that a later stage
        consumes by dot notation. A bare ``$lookup`` is a silent no-op.
        """
        rows = mcp.query("tries", [
            {"$lookup": {"from": "searchendpoints", "localField": "search_endpoint",
                         "foreignField": "id", "as": "ep"}},
            {"$match": {"ep.name": demo["endpoint"]["name"]}},
            {"$project": {"id": 1, "endpoint_name": "$ep.name"}},
        ])
        assert rows, "no try joined to the fixture's endpoint"
        assert rows[0]["endpoint_name"] == demo["endpoint"]["name"]

    def test_endpoint_url_is_returned_so_withholding_it_is_the_clients_job(
            self, mcp, demo):
        """"dont show url of server" is a prompt, not a server guarantee.

        ``fields`` on a toolset only builds the advertised schema -- the query
        ends at ``queryset.values()`` with no arguments, so every column of a
        published model comes back (CLAUDE.md; ``docs/mcp-server-plan.md``
        §3.2). This test states that plainly rather than letting anyone infer
        redaction that does not exist: the URL *is* on the wire, and only the
        assistant chose not to print it.
        """
        row = mcp.query("searchendpoints", [
            {"$match": {"id": demo["endpoint"]["id"]}},
        ])[0]
        assert row["endpoint_url"] == "http://search.invalid/solr/collection1/select"
        assert "basic_auth_credential" in row, (
            "searchendpoints no longer returns unadvertised columns -- if the "
            "library started honouring `fields`, docs/mcp-server-plan.md §3.2 "
            "and the CLAUDE.md warning both need revisiting"
        )


# ---------------------------------------------------------------------------
# Row scoping -- the "Not owner 2" grouping in the video
# ---------------------------------------------------------------------------

class TestScoping:
    """Unlike the REST routers, MCP restricts rows to the token owner.

    These need a non-administrator token: ``quepid_mcp/mcp.py:119`` short
    circuits for admins, so the same assertions with ``mcp`` would pass
    vacuously. They skip when ``QUEPID_MEMBER_API_TOKEN`` is unset.
    """

    def test_another_users_case_is_invisible(self, member_mcp, demo):
        rows = member_mcp.query("cases", [{"$match": {"id": demo["case"]["id"]}}])
        assert rows == [], (
            "a case owned by another user came back for a non-admin token -- "
            "scoping is not being applied"
        )

    def test_another_users_queries_are_invisible(self, member_mcp, demo):
        rows = member_mcp.query("queries", [
            {"$match": {"case": demo["case"]["id"]}},
        ])
        assert rows == []

    def test_empty_result_means_not_shared_not_missing(self, member_mcp, mcp, demo):
        """The same id, two tokens, two different answers.

        This is the distinction the server instructions ask clients to make,
        and it only holds if scoping is live.
        """
        assert mcp.query("cases", [{"$match": {"id": demo["case"]["id"]}}])
        assert not member_mcp.query("cases", [{"$match": {"id": demo["case"]["id"]}}])


# ---------------------------------------------------------------------------
# Quepid 8.5.0 upgrade guards
# ---------------------------------------------------------------------------

class TestUpgradeRegressions:
    """What the v8.4.0/v8.5.0 schema move changed on this surface."""

    def test_selectionstrategies_is_no_longer_published(self, mcp):
        """Quepid v8.4.0 dropped the table; the toolset went with it."""
        with pytest.raises(McpError):
            mcp.query("selectionstrategies", [{"$limit": 1}])

    def test_books_do_not_expose_columns_dropped_in_v840(self, mcp, book):
        if TARGET < (8, 4):
            pytest.skip("target predates the v8.4.0 books change")

        rows = mcp.query("books", [{"$match": {"id": book["id"]}}])
        assert rows, "the book created over REST is not visible over MCP"

        keys = set(rows[0])
        for dropped in ("scorer_id", "selection_strategy", "selection_strategy_id"):
            assert dropped not in keys, (
                f"books.{dropped} was dropped in Quepid v8.4.0 but MCP still "
                "returns it -- quepid/models.py has not been regenerated"
            )
        assert {"scale", "scale_with_labels", "scoring_guidelines"} <= keys

    def test_server_instructions_do_not_mention_dropped_things(self, mcp):
        """The prompt is data the model acts on; stale references misdirect it."""
        text = mcp.instructions().lower()
        assert "selectionstrateg" not in text
        assert "books.scorer_id" not in text

    def test_teams_junction_survives_composite_primary_keys(self, mcp):
        """``teamscases`` reflects as a ``CompositePrimaryKey`` since the 8.5.0
        regeneration (Django >= 5.2). Querying it must not raise, even empty."""
        assert isinstance(mcp.query("teamscases", [{"$limit": 1}]), list)
