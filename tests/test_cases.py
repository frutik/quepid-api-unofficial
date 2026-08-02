"""Integration tests for /api/case.

The ``cases`` table survives the v8.1.0 -> v8.5.0 move untouched, so nothing
here is version-gated. What these tests do carry is the API's two least obvious
behaviours:

- the request field is ``name`` but the response field is ``case_name``, because
  ``CreateCase`` renames it on the way into ``Cases.case_name``;
- ``create_case`` writes a ``tries`` row alongside the case, which is what makes
  a case runnable in Quepid at all. Nothing in this API exposes tries, so that
  side effect is only observable indirectly.
"""
import pytest
import requests

from conftest import BASE_URL, unique


pytestmark = pytest.mark.integration


def test_create_case(case):
    assert isinstance(case["id"], int)
    assert case["case_name"].startswith("case-test-")


def test_case_shape(case):
    assert {
        "id", "case_name", "last_try_number", "archived",
        "scorer_id", "book_id", "public", "nightly",
    } <= set(case)


def test_created_case_defaults(case):
    """create_case hardcodes these three rather than leaving them to Rails."""
    assert case["last_try_number"] == 1
    assert case["archived"] == 0
    assert case["nightly"] == 0  # the fixture asks for 0; the schema default is 1


def test_create_case_honours_nightly(api, scorer):
    """``nightly`` is what EnqueueRunNightlyCasesJob scopes on, Rails-side.

    ``Case.all.nightly_run`` is ``where(nightly: true)``, so a case created with
    nightly=1 is picked up by Quepid's 1am recurring job. That makes this column
    the one field in this API with a scheduling side effect, and CreateCase
    defaults it to 1 -- every case created through this API is nightly unless
    the caller says otherwise.
    """
    created = api.post(
        f"{BASE_URL}/case/",
        json={"name": unique("case"), "scorer_id": scorer["id"]},
        timeout=30,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    try:
        assert body["nightly"] == 1, "CreateCase.nightly no longer defaults to 1"
    finally:
        api.delete(f"{BASE_URL}/case/{body['id']}/", timeout=10)


def test_create_case_with_unknown_search_endpoint_is_400(api, scorer):
    """Rejects the request -- but the case row is already committed.

    ``create_case`` writes the ``Cases`` row first and only then resolves
    ``search_endpoint_id``, so this error path leaves an orphaned case behind
    with no try attached. This test asserts the status code it documents the
    leak; it deliberately does not assert on the orphan, but be aware that each
    run of this test adds one stray row to the database.
    """
    response = api.post(
        f"{BASE_URL}/case/",
        json={
            "name": unique("case-orphan"),
            "scorer_id": scorer["id"],
            "search_endpoint_id": 999999999,
        },
        timeout=30,
    )
    assert response.status_code == 400
    assert "Unknown search endpoint" in response.text


def test_get_case(api, case):
    response = api.get(f"{BASE_URL}/case/{case['id']}/", timeout=10)
    assert response.status_code == 200
    assert response.json()["id"] == case["id"]


def test_get_unknown_case_is_404(api):
    assert api.get(f"{BASE_URL}/case/999999999/", timeout=10).status_code == 404


def test_list_cases_is_paginated(api, case):
    response = api.get(f"{BASE_URL}/case/", timeout=30)
    assert response.status_code == 200
    assert {"items", "count"} <= set(response.json())


def test_update_case(api, case):
    renamed = unique("case-renamed")
    response = api.put(
        f"{BASE_URL}/case/{case['id']}/",
        json={"name": renamed, "archived": 1, "public": 1},
        timeout=10,
    )
    assert response.status_code == 200, response.text

    updated = response.json()
    assert updated["case_name"] == renamed
    assert updated["archived"] == 1
    assert updated["public"] == 1


def test_update_case_options_round_trips(api, case):
    """``cases.options`` is already a MySQL json column, hence JSONField.

    Contrast ``queries.options``, which is still TEXT at v8.1.0 and becomes json
    in v8.2.0 -- that difference is what the write path in api/queries.py has to
    catch up with. See tests/test_queries.py.
    """
    options = {"tie_breaker": "id asc", "depth": 10}
    response = api.put(
        f"{BASE_URL}/case/{case['id']}/", json={"options": options}, timeout=10
    )
    assert response.status_code == 200, response.text
    assert response.json()["options"] == options


def test_update_unknown_case_is_404(api):
    response = api.put(f"{BASE_URL}/case/999999999/", json={"name": "nope"}, timeout=10)
    assert response.status_code == 404


def test_delete_case_archives_rather_than_removing(api, case):
    """DELETE is a soft delete: 204, but the row survives with archived=1.

    A hard delete is impossible from here. ``create_case`` always writes a try,
    ``tries.case_id`` carries a real FK constraint, and ``inspectdb`` reflects
    every relation as ``DO_NOTHING`` -- so Django emits no cascade and MySQL
    answers with ``IntegrityError 1451``. Rails gets away with it via
    ``dependent: :destroy`` in ``app/models/case.rb:46``, which is model-level
    behaviour the reflection cannot see.
    """
    case_id = case["id"]
    assert case["archived"] == 0

    assert api.delete(f"{BASE_URL}/case/{case_id}/", timeout=10).status_code == 204

    fetched = api.get(f"{BASE_URL}/case/{case_id}/", timeout=10)
    assert fetched.status_code == 200, "archiving must not make the case unfetchable"
    assert fetched.json()["archived"] == 1


def test_delete_case_is_idempotent(api, case):
    """Archiving an already-archived case is a no-op, not an error."""
    case_id = case["id"]
    assert api.delete(f"{BASE_URL}/case/{case_id}/", timeout=10).status_code == 204
    assert api.delete(f"{BASE_URL}/case/{case_id}/", timeout=10).status_code == 204
    assert api.get(f"{BASE_URL}/case/{case_id}/", timeout=10).json()["archived"] == 1


def test_archived_case_can_be_restored(api, case):
    """``update_case`` already exposes ``archived``, so DELETE is reversible."""
    case_id = case["id"]
    api.delete(f"{BASE_URL}/case/{case_id}/", timeout=10)

    restored = api.put(f"{BASE_URL}/case/{case_id}/", json={"archived": 0}, timeout=10)
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived"] == 0


def _all_case_ids(api, archived=None):
    """Every case id across every page, so assertions do not depend on page size."""
    params = {"limit": 100}
    if archived is not None:
        params["archived"] = str(archived).lower()

    ids, offset = set(), 0
    while True:
        params["offset"] = offset
        body = api.get(f"{BASE_URL}/case/", params=params, timeout=30).json()
        ids.update(row["id"] for row in body["items"])
        offset += len(body["items"])
        if not body["items"] or offset >= body["count"]:
            return ids


def test_archived_case_disappears_from_the_default_list(api, case):
    """DELETE archives, and the default listing hides archived cases."""
    case_id = case["id"]
    assert case_id in _all_case_ids(api)

    api.delete(f"{BASE_URL}/case/{case_id}/", timeout=10)
    assert case_id not in _all_case_ids(api)


def test_archived_flag_lists_only_archived_cases(api, case):
    """``?archived=true`` is the complement of the default, not a superset."""
    case_id = case["id"]
    assert case_id not in _all_case_ids(api, archived=True)

    api.delete(f"{BASE_URL}/case/{case_id}/", timeout=10)
    assert case_id in _all_case_ids(api, archived=True)
    assert case_id not in _all_case_ids(api, archived=False)


def test_archived_false_is_the_default(api, case):
    """Passing archived=false explicitly matches passing nothing at all."""
    assert _all_case_ids(api) == _all_case_ids(api, archived=False)


def test_unarchiving_returns_a_case_to_the_default_list(api, case):
    case_id = case["id"]
    api.delete(f"{BASE_URL}/case/{case_id}/", timeout=10)
    assert case_id not in _all_case_ids(api)

    api.put(f"{BASE_URL}/case/{case_id}/", json={"archived": 0}, timeout=10)
    assert case_id in _all_case_ids(api)


# Not covered here: cases with archived = NULL. Rails declares the column as
# t.boolean "archived" -- nullable, no default -- so a case created through
# Quepid's own UI can be NULL, and view_cases excludes 1 rather than filtering
# on 0 precisely so those rows still count as "not archived". That third state
# is unreachable over HTTP: UpdateCase.archived is `int | None`, and update_case
# treats None as "leave alone", so nothing in this API can write a NULL. The
# behaviour is verified by reading the queryset, not by a test.


def test_delete_unknown_case_is_404(api):
    assert api.delete(f"{BASE_URL}/case/999999999/", timeout=10).status_code == 404


def test_cases_require_authentication(live_stack):
    assert requests.get(f"{BASE_URL}/case/", timeout=10).status_code == 401
