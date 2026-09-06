"""Integration tests for /api/books/{id}/query_doc_pairs.

A book's queries are not rows of their own: ``Book#queries_count`` is
``query_doc_pairs.select(:query_text).distinct.count``, so a query enters a book
only attached to a document. That single fact drives most of this module --
``doc_id`` is mandatory, identity is the ``(query_text, doc_id)`` pair, and
"how many queries does this book have" is a question about distinctness.

Quepid normally fills a book from a case run (``PopulateBookJob``). These routes
are the other direction: loading pairs that already exist, so a book can hold
ground truth rather than one engine's results.

Not to be confused with ``test_queries.py``: that covers ``queries``, which
belongs to a *case*.
"""
import pytest
import requests

from conftest import BASE_URL, fk_id


pytestmark = pytest.mark.integration


def _pairs_url(book):
    return f"{BASE_URL}/books/{book['id']}/query_doc_pairs/"


def _pair(query_text, doc_id, **extra):
    payload = {
        "query_text": query_text,
        "doc_id": doc_id,
        "document_fields": {"name": f"doc {doc_id}", "description": "fixture"},
    }
    payload.update(extra)
    return payload


def _all_pairs(api, book):
    """Every pair in the book, across every page."""
    rows, offset = [], 0
    while True:
        body = api.get(
            _pairs_url(book), params={"limit": 100, "offset": offset}, timeout=30
        ).json()
        rows += body["items"]
        offset += len(body["items"])
        if not body["items"] or offset >= body["count"]:
            return rows


@pytest.fixture
def pairs(api, book):
    """Three pairs over two queries, so distinctness is observable."""
    payload = [
        _pair("dinosaur toy", "doc-1", position=0),
        _pair("dinosaur toy", "doc-2", position=1),
        _pair("laptop stand", "doc-3", position=0),
    ]
    response = api.post(_pairs_url(book), json=payload, timeout=30)
    assert response.status_code == 200, response.text
    # The `book` fixture's teardown deletes the book, which now clears its pairs
    # first -- so there is nothing to undo here.
    return payload


def test_create_query_doc_pairs(api, book, pairs):
    assert len(_all_pairs(api, book)) == 3


def test_a_book_s_queries_are_the_distinct_query_texts(api, book, pairs):
    """Three pairs, two queries. This is what Book#queries_count counts."""
    rows = _all_pairs(api, book)
    assert len({row["query_text"] for row in rows}) == 2


def test_created_pairs_report_what_was_written(api, book):
    response = api.post(_pairs_url(book), json=[_pair("q", "d-1")], timeout=30)
    assert response.status_code == 200, response.text
    assert response.json() == {"created": 1, "skipped": 0}


def test_pair_shape(api, book, pairs):
    row = _all_pairs(api, book)[0]
    assert {
        "id", "query_text", "doc_id", "position",
        "document_fields", "query_options", "book",
    } <= set(row)
    assert fk_id(row, "book") == book["id"]


def test_document_fields_round_trip(api, book):
    """``document_fields`` is TEXT holding JSON, not a json column.

    ``PopulateBookJob`` writes ``pair[:document_fields].to_json`` into it, so
    the API has to dump on the way in and parse on the way out. Passing the dict
    straight to Django would store its Python repr, which Rails cannot read.
    Contrast ``options`` on the same row, which really is a MySQL json column.
    """
    fields = {"name": "Aluminium stand", "description": "adjustable", "price": 39}
    api.post(
        _pairs_url(book),
        json=[_pair("laptop stand", "doc-fields", document_fields=fields)],
        timeout=30,
    )
    row = next(r for r in _all_pairs(api, book) if r["doc_id"] == "doc-fields")
    assert row["document_fields"] == fields


def test_query_options_round_trip(api, book):
    """Where a foreign id has to live: the table has no column for one.

    PopulateBookJob copies a case query's ``options`` onto the pair of the same
    query_text, so a value stored here survives the book being populated from a
    case as well.
    """
    api.post(
        _pairs_url(book),
        json=[_pair("dinosaur toy", "doc-opts", query_options={"esci_query_id": 42})],
        timeout=30,
    )
    row = next(r for r in _all_pairs(api, book) if r["doc_id"] == "doc-opts")
    assert row["query_options"] == {"esci_query_id": 42}


def test_pairs_without_options_read_back_as_an_empty_dict(api, book, pairs):
    """Mirrors Query.query_options: absent JSON is {}, never None."""
    assert all(row["query_options"] == {} for row in _all_pairs(api, book))


def test_reposting_the_same_batch_creates_nothing(api, book, pairs):
    """Identity is (query_text, doc_id) -- the find_or_create_by PopulateBookJob uses.

    Which makes the import re-runnable: a notebook cell that loads a dataset can
    be run twice without doubling the book.
    """
    response = api.post(_pairs_url(book), json=pairs, timeout=30)
    assert response.json() == {"created": 0, "skipped": 3}
    assert len(_all_pairs(api, book)) == 3


def test_duplicates_within_one_batch_are_collapsed(api, book):
    """The batch is de-duplicated against itself, not only against the book.

    Nothing is written until the bulk insert at the end, so a repeat inside the
    payload cannot be caught by re-reading the table.
    """
    duplicated = [_pair("q", "same-doc"), _pair("q", "same-doc")]
    assert api.post(_pairs_url(book), json=duplicated, timeout=30).json() == {
        "created": 1, "skipped": 1
    }
    assert len(_all_pairs(api, book)) == 1


def test_same_doc_under_a_different_query_is_a_separate_pair(api, book):
    """Identity is the pair, not the document: one doc can answer many queries."""
    api.post(
        _pairs_url(book),
        json=[_pair("query one", "shared-doc"), _pair("query two", "shared-doc")],
        timeout=30,
    )
    assert len(_all_pairs(api, book)) == 2


def test_pairs_are_scoped_to_their_book(api, book, book_payload, pairs):
    """A second book does not see the first one's pairs."""
    other = api.post(f"{BASE_URL}/books/", json={**book_payload, "name": "other"},
                     timeout=30).json()
    try:
        assert _all_pairs(api, other) == []
    finally:
        api.delete(f"{BASE_URL}/books/{other['id']}", timeout=10)


def test_doc_id_is_required(api, book):
    """Rails validates ``doc_id`` presence, so the schema must too.

    Without it this API could write rows Quepid itself considers invalid: the
    column is nullable in MySQL and only the model objects.
    """
    response = api.post(
        _pairs_url(book), json=[{"query_text": "no doc here"}], timeout=30
    )
    assert response.status_code == 422


def test_query_text_is_required(api, book):
    response = api.post(_pairs_url(book), json=[{"doc_id": "d-1"}], timeout=30)
    assert response.status_code == 422


def test_writing_to_an_unknown_book_is_404(api):
    response = api.post(
        f"{BASE_URL}/books/999999999/query_doc_pairs/",
        json=[_pair("q", "d")],
        timeout=30,
    )
    assert response.status_code == 404


def test_reading_an_unknown_book_is_empty(api):
    """Reads are unscoped across this router, so an unknown book is simply empty."""
    body = api.get(f"{BASE_URL}/books/999999999/query_doc_pairs/", timeout=30).json()
    assert body["items"] == []


def test_a_stranger_cannot_write_to_your_book(member_api, book):
    """Writes are owner-or-team, unlike the reads in this router.

    Adding pairs to somebody else's book changes what their judges are asked to
    rate, which is a good deal more than reading it.
    """
    response = member_api.post(_pairs_url(book), json=[_pair("q", "d")], timeout=30)
    assert response.status_code == 404


def test_a_stranger_cannot_clear_your_book(member_api, book, pairs):
    assert member_api.delete(_pairs_url(book), timeout=30).status_code == 404


def test_delete_clears_the_book(api, book, pairs):
    response = api.delete(_pairs_url(book), timeout=30)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 3}
    assert _all_pairs(api, book) == []


def test_delete_is_idempotent(api, book, pairs):
    api.delete(_pairs_url(book), timeout=30)
    assert api.delete(_pairs_url(book), timeout=30).json() == {"deleted": 0}


def test_clearing_lets_a_pair_be_reimported_with_new_documents(api, book):
    """The reason delete exists: create skips known pairs, it does not update them."""
    api.post(_pairs_url(book), json=[_pair("q", "d", document_fields={"name": "old"})],
             timeout=30)
    api.delete(_pairs_url(book), timeout=30)
    api.post(_pairs_url(book), json=[_pair("q", "d", document_fields={"name": "new"})],
             timeout=30)

    assert _all_pairs(api, book)[0]["document_fields"] == {"name": "new"}


def test_a_book_holding_pairs_can_still_be_deleted(api, book_payload):
    """``query_doc_pairs.book_id`` is a real FK, so delete_book has to cascade.

    Before it did, this API could create a book it could never delete: one pair
    was enough for MySQL to answer 1451 and the DELETE to return 400.
    """
    book = api.post(f"{BASE_URL}/books/", json=book_payload, timeout=30).json()
    api.post(_pairs_url(book), json=[_pair("q", "d")], timeout=30)

    response = api.delete(f"{BASE_URL}/books/{book['id']}", timeout=30)
    assert response.status_code == 200, response.text
    assert api.get(f"{BASE_URL}/books/{book['id']}", timeout=10).status_code == 404


def test_query_doc_pairs_require_authentication(live_stack, book):
    url = f"{BASE_URL}/books/{book['id']}/query_doc_pairs/"
    assert requests.get(url, timeout=10).status_code == 401
    assert requests.post(url, json=[], timeout=10).status_code == 401


def test_deleting_a_book_releases_its_cases(api, book_payload, case):
    """``cases.book_id`` has no foreign key, so nothing would catch a dangling one.

    Rails declares ``has_many :cases, dependent: :nullify`` -- the case survives
    its book, because a case is a search configuration and outlives whatever it
    was being rated against. Without the same behaviour here, deleting a book
    left every case that used it pointing at an id that no longer resolves, with
    no constraint to complain.
    """
    book = api.post(f"{BASE_URL}/books/", json=book_payload, timeout=30).json()
    api.put(f"{BASE_URL}/case/{case['id']}/", json={"book_id": book["id"]}, timeout=10)

    api.delete(f"{BASE_URL}/books/{book['id']}", timeout=30)

    released = api.get(f"{BASE_URL}/case/{case['id']}/", timeout=10)
    assert released.status_code == 200, "the case must survive its book"
    assert released.json()["book_id"] is None
