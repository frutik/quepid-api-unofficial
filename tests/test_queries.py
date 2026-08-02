"""Integration tests for /api/query.

Route shapes here are unlike the rest of the API: every path is nested under a
case id, and the detail routes carry no trailing slash
(``/api/query/{case_id}/{query_id}``) while the collection routes do. These
tests use the routes exactly as declared rather than normalising them.

A note on what this module does *not* cover, because it matters for the v8.5.0
upgrade: see ``test_query_options_round_trip``.
"""
import pytest
import requests

from conftest import BASE_URL, fk_id, unique


pytestmark = pytest.mark.integration


def _patch_body(**overrides):
    """A complete UpdateQuery body.

    ``UpdateQuery`` declares its fields as bare ``Optional[str]`` with no
    default, which in pydantic v2 means *required, may be null* -- not
    *optional*. So a PATCH must carry all four keys. Compare ``UpdateBook`` and
    ``UpdateCase``, which use ``= None`` and are genuinely partial.
    """
    body = {
        "query_text": None,
        "notes": None,
        "information_need": None,
        "query_options": None,
    }
    body.update(overrides)
    return body


def test_create_query(query):
    assert isinstance(query["id"], int)
    assert query["query_text"] == "wingback armchair"


def test_query_shape(query):
    assert {"id", "query_text", "notes", "information_need", "query_options"} <= set(query)


def test_query_options_is_exposed_instead_of_options(query):
    """``Query`` excludes the raw ``options`` column and surfaces a dict.

    ``quepid/schemas.py`` sets ``exclude = ['options']`` and adds a
    ``query_options: dict`` resolver, so the serialized text column never
    reaches the client as text.
    """
    assert "options" not in query
    assert isinstance(query["query_options"], dict)


def test_query_options_round_trip(api, case):
    """Options given at create time come back as a dict.

    **This test cannot detect the v8.2.0 json-column drift**, and that is worth
    stating rather than discovering later. When ``queries.options`` becomes a
    MySQL json column, ``inspectdb`` regenerates it as a JSONField, and
    ``api/queries.py:61``'s ``json.dumps(...)`` then double-encodes on write.
    But ``resolve_query_options`` falls back to ``json.loads`` for non-dict
    values, so it silently recovers -- the REST response is byte-identical in
    both the broken and the fixed world.

    What the double-encoding does break is *Quepid*, which reads the column
    expecting a Hash and gets a String, and the MCP ``queries`` collection,
    which returns ``queryset.values()`` with no resolver in front of it.
    Verifying that fix means inspecting the stored column or querying over MCP,
    not calling this endpoint.
    """
    options = {"fq": "in_stock:true", "rows": 20}
    created = api.post(
        f"{BASE_URL}/query/{case['id']}/",
        json={"query_text": "chaise longue", "query_options": options},
        timeout=30,
    )
    assert created.status_code == 200, created.text

    body = created.json()
    try:
        assert body["query_options"] == options
        fetched = api.get(
            f"{BASE_URL}/query/{case['id']}/{body['id']}", timeout=10
        ).json()
        assert fetched["query_options"] == options
    finally:
        api.delete(f"{BASE_URL}/query/{case['id']}/{body['id']}", timeout=10)


def test_query_without_options_returns_empty_dict(api, case):
    """create_query stores NULL for a falsy options dict; the resolver maps it to {}."""
    created = api.post(
        f"{BASE_URL}/query/{case['id']}/",
        json={"query_text": "no options here"},
        timeout=30,
    )
    assert created.status_code == 200, created.text

    body = created.json()
    try:
        assert body["query_options"] == {}
    finally:
        api.delete(f"{BASE_URL}/query/{case['id']}/{body['id']}", timeout=10)


def test_query_belongs_to_its_case(query, case):
    assert fk_id(query, "case") == case["id"]


def test_create_query_on_unknown_case_is_400(api):
    response = api.post(
        f"{BASE_URL}/query/999999999/", json={"query_text": "orphan"}, timeout=30
    )
    assert response.status_code == 400
    assert "Unknown case" in response.text


def test_get_query(api, case, query):
    response = api.get(f"{BASE_URL}/query/{case['id']}/{query['id']}", timeout=10)
    assert response.status_code == 200
    assert response.json()["id"] == query["id"]


def test_get_unknown_query_is_404(api, case):
    response = api.get(f"{BASE_URL}/query/{case['id']}/999999999", timeout=10)
    assert response.status_code == 404


def test_list_queries_for_case(api, case, query):
    response = api.get(f"{BASE_URL}/query/{case['id']}/", timeout=30)
    assert response.status_code == 200

    body = response.json()
    assert {"items", "count"} <= set(body)
    assert query["id"] in {row["id"] for row in body["items"]}


def test_list_queries_is_scoped_to_the_case(api, case, query, scorer):
    """view_queries filters on case_id, so another case sees none of these."""
    other = api.post(
        f"{BASE_URL}/case/",
        json={"name": unique("case-other"), "scorer_id": scorer["id"], "nightly": 0},
        timeout=30,
    )
    assert other.status_code == 200, other.text
    other_id = other.json()["id"]

    try:
        body = api.get(f"{BASE_URL}/query/{other_id}/", timeout=30).json()
        assert query["id"] not in {row["id"] for row in body["items"]}
    finally:
        api.delete(f"{BASE_URL}/case/{other_id}/", timeout=10)


def test_update_query(api, case, query):
    response = api.patch(
        f"{BASE_URL}/query/{case['id']}/{query['id']}",
        json=_patch_body(query_text="loveseat", notes="renamed by test"),
        timeout=10,
    )
    assert response.status_code == 200, response.text

    updated = response.json()
    assert updated["query_text"] == "loveseat"
    assert updated["notes"] == "renamed by test"


def test_partial_update_is_rejected(api, case, query):
    """Documents the UpdateQuery required-fields quirk described in _patch_body.

    If this ever returns 200, someone gave UpdateQuery proper ``= None``
    defaults -- delete this test and simplify ``_patch_body``.
    """
    response = api.patch(
        f"{BASE_URL}/query/{case['id']}/{query['id']}",
        json={"query_text": "partial"},
        timeout=10,
    )
    assert response.status_code == 422


def test_update_unknown_query_is_404(api, case):
    response = api.patch(
        f"{BASE_URL}/query/{case['id']}/999999999",
        json=_patch_body(query_text="nope"),
        timeout=10,
    )
    assert response.status_code == 404


def test_delete_query(api, case):
    created = api.post(
        f"{BASE_URL}/query/{case['id']}/", json={"query_text": "doomed"}, timeout=30
    )
    assert created.status_code == 200, created.text
    query_id = created.json()["id"]

    deleted = api.delete(f"{BASE_URL}/query/{case['id']}/{query_id}", timeout=10)
    assert deleted.status_code == 200
    assert deleted.json() == {"message": "Query deleted successfully"}
    assert api.get(
        f"{BASE_URL}/query/{case['id']}/{query_id}", timeout=10
    ).status_code == 404


def test_queries_require_authentication(live_stack):
    assert requests.get(f"{BASE_URL}/query/1/", timeout=10).status_code == 401
