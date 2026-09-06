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
        json={
            "name": unique("case"),
            "scorer_id": scorer["id"],
            "team_id": 0,   # unshared: see the `case` fixture in conftest
        },
        timeout=30,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    try:
        assert body["nightly"] == 1, "CreateCase.nightly no longer defaults to 1"
    finally:
        api.delete(f"{BASE_URL}/case/{body['id']}/", timeout=10)


def test_create_case_with_unknown_search_endpoint_is_400(api, scorer):
    """Rejects the request, and leaves nothing behind.

    ``create_case`` used to write the ``Cases`` row first and resolve
    ``search_endpoint_id`` only afterwards, so this error path returned 400
    having already committed an orphaned case with no try attached -- one stray
    row per run of this test. It now validates before it writes and wraps the
    case, its try and any team association in one transaction, so the second
    assertion here is the one that matters.
    """
    # The total, not the first page: the listing is paginated, so a leaked case
    # could sit on a later page and a name check would miss it.
    before = api.get(f"{BASE_URL}/case/", timeout=30).json()["count"]

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

    after = api.get(f"{BASE_URL}/case/", timeout=30).json()["count"]
    assert after == before, "rejected case leaked"


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


# --- book_id ----------------------------------------------------------------


def test_create_case_attaches_the_book(api, scorer, book):
    """``CreateCase.book_id`` reaches the row it names.

    It was declared on the schema but never passed to the insert, so a case
    asking for a book was created without one -- 200, no error, and a `book_id`
    of null in the very response that had just been asked for a book. The only
    symptom was downstream: nothing linked the case to the book it was meant to
    be rated into.
    """
    created = api.post(
        f"{BASE_URL}/case/",
        json={
            "name": unique("case"),
            "scorer_id": scorer["id"],
            "book_id": book["id"],
            "team_id": 0,
        },
        timeout=30,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    try:
        assert body["book_id"] == book["id"]
        fetched = api.get(f"{BASE_URL}/case/{body['id']}/", timeout=10).json()
        assert fetched["book_id"] == book["id"], "the link did not survive the read"
    finally:
        api.delete(f"{BASE_URL}/case/{body['id']}/", timeout=10)


def test_create_case_without_a_book_leaves_it_null(case):
    """The default stays what it was: a case need not belong to a book."""
    assert case["book_id"] is None


def test_create_case_with_an_unknown_book_is_400(api, scorer):
    """Validated before the write, like search_endpoint_id, and leaving nothing."""
    before = api.get(f"{BASE_URL}/case/", timeout=30).json()["count"]

    response = api.post(
        f"{BASE_URL}/case/",
        json={"name": unique("case"), "scorer_id": scorer["id"], "book_id": 999999999,
              "team_id": 0},
        timeout=30,
    )
    assert response.status_code == 400
    assert "book" in response.text.lower()

    after = api.get(f"{BASE_URL}/case/", timeout=30).json()["count"]
    assert after == before, "rejected case leaked"


def test_a_case_cannot_be_pointed_at_a_stranger_s_book(member_api, scorer, book):
    """Existence is not enough: it has to be a book the caller can reach.

    A case attached to a book is what PopulateBookJob writes query/doc pairs
    into, so accepting any book id would let a caller feed rows into a book they
    cannot see -- the same reasoning as the write scoping in api/books.py.
    """
    own_scorer = member_api.post(
        f"{BASE_URL}/scorers/", json={"name": unique("scorer")}, timeout=30
    ).json()
    response = member_api.post(
        f"{BASE_URL}/case/",
        json={"name": unique("case"), "scorer_id": own_scorer["id"],
              "book_id": book["id"], "team_id": 0},
        timeout=30,
    )
    member_api.delete(f"{BASE_URL}/scorers/{own_scorer['id']}/", timeout=10)
    assert response.status_code == 400


def test_update_case_attaches_and_detaches_a_book(api, case, book):
    attached = api.put(
        f"{BASE_URL}/case/{case['id']}/", json={"book_id": book["id"]}, timeout=10
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["book_id"] == book["id"]

    # 0 detaches, the state delete_book leaves a case in.
    detached = api.put(f"{BASE_URL}/case/{case['id']}/", json={"book_id": 0}, timeout=10)
    assert detached.status_code == 200, detached.text
    assert detached.json()["book_id"] is None


def test_update_case_with_an_unknown_book_is_400(api, case):
    response = api.put(
        f"{BASE_URL}/case/{case['id']}/", json={"book_id": 999999999}, timeout=10
    )
    assert response.status_code == 400
    assert api.get(f"{BASE_URL}/case/{case['id']}/", timeout=10).json()["book_id"] is None
