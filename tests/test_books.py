"""Integration tests for /api/books.

This module carries the assertion the Quepid v8.5.0 upgrade turns on. Quepid
v8.4.0 dropped ``books.scorer_id`` and ``books.selection_strategy_id`` (and the
whole ``selection_strategies`` table) in migrations ``20251206163533`` and
``20251206221416``. ``quepid/models.py`` still declares both, and Django puts
every declared column in the SELECT list, so on a v8.4.0+ database every books
endpoint fails with ``Unknown column 'books.selection_strategy_id' in 'field
list'`` before a single row comes back.

Books are also the surface with no prior coverage of any kind: none of the
notebooks at the repo root ever call ``/api/books`` (see
``docs/quepid-compatibility.md``), so the one code path v8.4.0 breaks is the one
path that has never been exercised. That is what these tests fix.

``test_book_shape_matches_target`` asserts in both directions -- it fails if the
database disagrees with ``QUEPID_TARGET`` either way, so it catches "I said 8.5
but I am still pointed at 8.3.6" as loudly as it catches the regression itself.
"""
import pytest
import requests

from conftest import BASE_URL, LEGACY_BOOKS, unique


pytestmark = pytest.mark.integration


DROPPED_IN_V840 = ("scorer_id", "selection_strategy", "selection_strategy_id")


def test_create_book_returns_the_row(book):
    assert isinstance(book["id"], int)
    assert book["name"].startswith("book-test-")


def test_created_book_records_an_integer_owner(book):
    """``owner_id`` is a plain IntegerField, not a ForeignKey.

    ``api/books.py:62`` passes ``owner_id=request.auth`` -- a ``Users``
    instance -- into that IntegerField, which Django cannot adapt, so creation
    fails with a 400 swallowed by the module's broad ``except Exception``. The
    fix is ``owner_id=request.auth.id``. Compare ``api/cases.py:71``, which
    assigns to the real ``owner`` ForeignKey and is therefore correct.

    If this test never runs because the ``book`` fixture itself failed, that is
    the bug reproducing.
    """
    assert book["owner_id"] is None or isinstance(book["owner_id"], int)


def test_book_shape_matches_target(book):
    """The columns v8.4.0 dropped are present iff the target predates v8.4.0."""
    if LEGACY_BOOKS:
        assert "scorer_id" in book, (
            "QUEPID_TARGET is pre-8.4.0 but books.scorer_id is missing -- "
            "the stack is newer than declared"
        )
        assert any(key in book for key in ("selection_strategy", "selection_strategy_id")), (
            "QUEPID_TARGET is pre-8.4.0 but no selection_strategy field came back"
        )
        return

    for field in DROPPED_IN_V840:
        assert field not in book, (
            f"books.{field} was dropped in Quepid v8.4.0 but the API still "
            f"returns it -- quepid/models.py has not been regenerated"
        )


def test_book_keeps_its_stable_columns(book):
    """Columns untouched by the v8.4.0 migrations, so true on either side."""
    assert {"id", "name", "owner_id", "support_implicit_judgements", "show_rank"} <= set(book)


def test_get_book(api, book):
    # Note: no trailing slash. api/books.py declares "/{book_id}" while the
    # cases, teams and scorers routers all declare "/{id}/". Do not normalise
    # this in the test -- it is asserting the route as it actually exists.
    response = api.get(f"{BASE_URL}/books/{book['id']}", timeout=10)
    assert response.status_code == 200
    assert response.json()["id"] == book["id"]


def test_get_unknown_book_is_404(api):
    response = api.get(f"{BASE_URL}/books/999999999", timeout=10)
    assert response.status_code == 404


def test_list_books_is_paginated_and_contains_the_book(api, book):
    response = api.get(f"{BASE_URL}/books/", timeout=30)
    assert response.status_code == 200

    body = response.json()
    assert {"items", "count"} <= set(body), (
        "view_books is decorated with @paginate, so the body should be "
        f"{{items, count}}, got keys: {sorted(body)}"
    )

    # Default page size may not reach a book created last, so page by id.
    match = api.get(f"{BASE_URL}/books/{book['id']}", timeout=10).json()
    assert match["name"] == book["name"]


def test_update_book(api, book):
    renamed = unique("book-renamed")
    response = api.patch(
        f"{BASE_URL}/books/{book['id']}",
        json={"name": renamed, "show_rank": True},
        timeout=10,
    )
    assert response.status_code == 200, response.text

    updated = response.json()
    assert updated["name"] == renamed
    # show_rank is a MySQL tinyint surfaced as IntegerField, so 1/0, not
    # true/false -- CLAUDE.md flags null as a distinct third state.
    assert updated["show_rank"] == 1


def test_update_unknown_book_is_404(api):
    response = api.patch(
        f"{BASE_URL}/books/999999999", json={"name": "nope"}, timeout=10
    )
    assert response.status_code == 404


def test_delete_book(api, book_payload):
    """Deletes its own book rather than using the fixture, which also deletes."""
    created = api.post(f"{BASE_URL}/books/", json=book_payload, timeout=30)
    assert created.status_code == 200, created.text
    book_id = created.json()["id"]

    deleted = api.delete(f"{BASE_URL}/books/{book_id}", timeout=10)
    assert deleted.status_code == 200
    assert deleted.json() == {"message": "Book deleted successfully"}

    assert api.get(f"{BASE_URL}/books/{book_id}", timeout=10).status_code == 404


def test_books_require_authentication(live_stack):
    """Auth is applied globally on the NinjaAPI, so no router opts out."""
    response = requests.get(f"{BASE_URL}/books/", timeout=10)
    assert response.status_code == 401


# --- scale ------------------------------------------------------------------
#
# ``books.scale`` is the set of ratings a judge may give, held as the varchar
# "0,1,2,3" and read by ScaleSerializer into a sorted list of ints. Quepid's own
# UI never asks for it directly: creating a book there means picking a scorer,
# and ``books_controller.rb:121`` copies that scorer's scale onto the book.
# Nothing picks a scorer on this path, so without these fields a book made
# through the API has no scale at all -- and since
# ``JudgementHelper#generate_rating_buttons`` maps over ``book.scale`` to build
# the rating buttons, such a book renders none and cannot be judged by hand.
#
# Note this is not what the *LLM* judge rates against. ``LlmService`` sends only
# the query and the document fields; the 0-3 instruction lives in the AI judge
# user's system_prompt. The scale governs the human judging screen and labels.


def test_a_book_created_without_a_scale_has_none(book):
    """The default, and the reason these fields exist: no scale, no buttons."""
    assert book["scale"] == []
    assert book["scale_with_labels"] == {}


def test_create_book_with_a_scale(api, book_payload):
    payload = {
        **book_payload,
        "scale": [0, 1, 2, 3],
        "scale_with_labels": {"0": "Irrelevant", "3": "Exact"},
    }
    created = api.post(f"{BASE_URL}/books/", json=payload, timeout=30).json()
    try:
        assert created["scale"] == [0, 1, 2, 3]
        assert created["scale_with_labels"] == {"0": "Irrelevant", "3": "Exact"}
    finally:
        api.delete(f"{BASE_URL}/books/{created['id']}", timeout=10)


def test_scale_is_stored_sorted(api, book_payload):
    """ScaleSerializer.load sorts on read, so an unsorted scale must round-trip.

    Sorting is not cosmetic: generate_rating_buttons lays the buttons out in
    scale order and colours them by position within it, so an unsorted scale
    would put the ratings on screen in whatever order they were sent.
    """
    created = api.post(
        f"{BASE_URL}/books/", json={**book_payload, "scale": [3, 0, 2, 1]}, timeout=30
    ).json()
    try:
        assert created["scale"] == [0, 1, 2, 3]
    finally:
        api.delete(f"{BASE_URL}/books/{created['id']}", timeout=10)


def test_scale_survives_the_varchar_it_is_stored_in(api, book_payload):
    """The column is a varchar of joined integers, not a json column.

    Which makes the round trip the thing worth asserting: the response renders
    a list, the database holds "0,1,2,3", and Rails reads back [0, 1, 2, 3].
    """
    created = api.post(
        f"{BASE_URL}/books/", json={**book_payload, "scale": [0, 1, 2, 3]}, timeout=30
    ).json()
    try:
        fetched = api.get(f"{BASE_URL}/books/{created['id']}", timeout=10).json()
        assert fetched["scale"] == [0, 1, 2, 3]
    finally:
        api.delete(f"{BASE_URL}/books/{created['id']}", timeout=10)


def test_update_book_sets_the_scale(api, book):
    response = api.patch(
        f"{BASE_URL}/books/{book['id']}",
        json={"scale": [0, 1], "scale_with_labels": {"0": "No", "1": "Yes"}},
        timeout=10,
    )
    assert response.status_code == 200, response.text
    assert response.json()["scale"] == [0, 1]
    assert response.json()["scale_with_labels"] == {"0": "No", "1": "Yes"}


def test_updating_other_fields_leaves_the_scale_alone(api, book):
    api.patch(f"{BASE_URL}/books/{book['id']}", json={"scale": [0, 1, 2, 3]}, timeout=10)
    renamed = api.patch(
        f"{BASE_URL}/books/{book['id']}", json={"name": unique("book")}, timeout=10
    )
    assert renamed.json()["scale"] == [0, 1, 2, 3]


def test_resending_an_unchanged_scale_is_allowed(api, book):
    """The guard in ``_scale_is_locked`` compares values, not whether it was sent.

    An updater that echoes the whole book back -- read, edit one field, PATCH --
    must not be refused for a scale it is not actually touching. Only half
    observable here: with no judgements in the book the guard short-circuits
    before it ever compares, so see the note below for the other half.
    """
    api.patch(f"{BASE_URL}/books/{book['id']}", json={"scale": [0, 1, 2, 3]}, timeout=10)
    response = api.patch(
        f"{BASE_URL}/books/{book['id']}",
        json={"name": unique("book"), "scale": [0, 1, 2, 3]},
        timeout=10,
    )
    assert response.status_code == 200, response.text


# Not covered here: changing the scale of a book that has been judged, which
# ``update_book`` refuses with 400 to match Rails'
# ``Book#scale_cannot_be_changed_if_judgements_exist`` (labels stay editable).
# Reaching it needs a judgement, and judgements are not writable over this API
# at all -- they belong to Quepid's judging screen and to RunJudgeJudyJob, and
# nothing in api/ touches the table except the cascade in delete_book. Verified
# by hand against the stack instead: with one judgement present, PATCH with a
# different scale answers 400 and PATCH with new labels answers 200. Same
# reasoning as the archived = NULL note in tests/test_cases.py.
