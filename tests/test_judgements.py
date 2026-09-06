"""Integration tests for /api/books/{id}/judgements.

A judgement is one rater's verdict on one query/doc pair, and the table is keyed
on ``(user_id, query_doc_pair_id)`` -- so several raters judge the same pair
independently. That is the point of these routes: an already-labelled dataset
goes in as one rater's judgements, an AI judge adds its own, and the two can
then be compared pair by pair.

Not to be confused with ``test_ratings.py``: a rating hangs off a *case* query
and is what a scorer reads. A judgement hangs off a book's pair.
"""
import pytest

from conftest import BASE_URL, unique


pytestmark = pytest.mark.integration


def _judgements_url(book, **params):
    url = f"{BASE_URL}/books/{book['id']}/judgements/"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    return url


def _pairs_url(book):
    return f"{BASE_URL}/books/{book['id']}/query_doc_pairs/"


@pytest.fixture
def judged_book(api, book):
    """A book holding three pairs on one query, ready to be judged.

    The book's scale is set here because ``create_judgements`` checks ratings
    against it -- and because a book made through this API has no scale unless
    something says so.
    """
    api.patch(
        f"{BASE_URL}/books/{book['id']}",
        json={"scale": [0, 1, 2, 3]},
        timeout=10,
    )
    api.post(
        _pairs_url(book),
        json=[
            {"query_text": "farm animals", "doc_id": f"doc-{n}",
             "document_fields": {"name": f"doc {n}"}}
            for n in range(1, 4)
        ],
        timeout=30,
    )
    return book


def _judgement(doc_id, **extra):
    payload = {"query_text": "farm animals", "doc_id": doc_id, "rating": 3}
    payload.update(extra)
    return payload


def test_judgements_are_loaded_in_bulk(api, judged_book):
    response = api.post(
        _judgements_url(judged_book),
        json=[_judgement("doc-1", rating=3), _judgement("doc-2", rating=0)],
        timeout=30,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"created": 2, "updated": 0,
                               "unchanged": 0, "unknown": 0}


def test_a_loaded_judgement_reads_back(api, judged_book):
    api.post(
        _judgements_url(judged_book),
        json=[_judgement("doc-1", rating=2, explanation="substitute")],
        timeout=30,
    )

    listed = api.get(_judgements_url(judged_book), timeout=10).json()["items"]
    assert len(listed) == 1
    assert listed[0]["rating"] == 2
    assert listed[0]["explanation"] == "substitute"


def test_reposting_the_same_verdict_changes_nothing(api, judged_book):
    """Identity is (rater, pair), so a re-run is a no-op rather than a duplicate."""
    body = [_judgement("doc-1", rating=3, explanation="exact")]
    api.post(_judgements_url(judged_book), json=body, timeout=30)

    again = api.post(_judgements_url(judged_book), json=body, timeout=30)
    assert again.json() == {"created": 0, "updated": 0,
                            "unchanged": 1, "unknown": 0}
    assert len(api.get(_judgements_url(judged_book), timeout=10).json()["items"]) == 1


def test_a_changed_rating_updates_in_place(api, judged_book):
    api.post(_judgements_url(judged_book),
             json=[_judgement("doc-1", rating=3)], timeout=30)

    response = api.post(_judgements_url(judged_book),
                        json=[_judgement("doc-1", rating=1)], timeout=30)
    assert response.json() == {"created": 0, "updated": 1,
                               "unchanged": 0, "unknown": 0}

    listed = api.get(_judgements_url(judged_book), timeout=10).json()["items"]
    assert len(listed) == 1
    assert listed[0]["rating"] == 1


def test_a_pair_the_book_does_not_hold_is_counted_not_raised(api, judged_book):
    """One stale row should not reject a batch of 500 -- but must be visible."""
    response = api.post(
        _judgements_url(judged_book),
        json=[_judgement("doc-1"), _judgement("doc-404")],
        timeout=30,
    )
    assert response.json()["created"] == 1
    assert response.json()["unknown"] == 1


def test_a_query_text_that_does_not_match_is_unknown(api, judged_book):
    """Pairs are addressed by both halves of the key, not by doc_id alone."""
    response = api.post(
        _judgements_url(judged_book),
        json=[{"query_text": "barn animals", "doc_id": "doc-1", "rating": 3}],
        timeout=30,
    )
    assert response.json() == {"created": 0, "updated": 0,
                               "unchanged": 0, "unknown": 1}


def test_a_batch_naming_one_pair_twice_writes_one_row(api, judged_book):
    """The unique index would refuse the second write, so it never happens."""
    response = api.post(
        _judgements_url(judged_book),
        json=[_judgement("doc-1", rating=3), _judgement("doc-1", rating=0)],
        timeout=30,
    )
    assert response.status_code == 200, response.text
    assert len(api.get(_judgements_url(judged_book), timeout=10).json()["items"]) == 1


def test_a_rating_off_the_books_scale_is_refused(api, judged_book):
    """The judging screen builds its buttons from the scale.

    A rating outside it is a row nobody can see or change by hand afterwards,
    which is worse than a rejected write.
    """
    response = api.post(_judgements_url(judged_book),
                        json=[_judgement("doc-1", rating=7)], timeout=30)
    assert response.status_code == 400, response.text
    assert "scale" in response.json()


def test_a_judgement_needs_a_rating(api, judged_book):
    response = api.post(
        _judgements_url(judged_book),
        json=[{"query_text": "farm animals", "doc_id": "doc-1"}],
        timeout=30,
    )
    assert response.status_code == 400, response.text


def test_unrateable_needs_no_rating(api, judged_book):
    """"I can't tell" is a deliberate non-answer, not a missing one."""
    response = api.post(
        _judgements_url(judged_book),
        json=[{"query_text": "farm animals", "doc_id": "doc-1",
               "unrateable": True}],
        timeout=30,
    )
    assert response.status_code == 200, response.text

    listed = api.get(_judgements_url(judged_book), timeout=10).json()["items"]
    assert listed[0]["rating"] is None
    assert listed[0]["unrateable"] == 1


def test_judge_later_needs_no_rating(api, judged_book):
    response = api.post(
        _judgements_url(judged_book),
        json=[{"query_text": "farm animals", "doc_id": "doc-1",
               "judge_later": True}],
        timeout=30,
    )
    assert response.status_code == 200, response.text
    assert api.get(_judgements_url(judged_book), timeout=10).json()["items"][0]["judge_later"] == 1


def test_the_flags_are_written_as_false_not_null(api, judged_book):
    """Rails' ``rateable`` scope is ``where(unrateable: false)``.

    NULL does not satisfy that, so a NULL here would quietly drop the
    judgement out of every count that scope feeds.
    """
    api.post(_judgements_url(judged_book),
             json=[_judgement("doc-1", rating=3)], timeout=30)

    listed = api.get(_judgements_url(judged_book), timeout=10).json()["items"]
    assert listed[0]["unrateable"] == 0
    assert listed[0]["judge_later"] == 0


def test_judgements_are_the_callers_own_by_default(api, judged_book, case):
    from conftest import fk_id

    api.post(_judgements_url(judged_book),
             json=[_judgement("doc-1", rating=3)], timeout=30)

    listed = api.get(_judgements_url(judged_book), timeout=10).json()["items"]
    assert fk_id(listed[0], "user") == fk_id(case, "owner")


def test_judgements_can_be_anonymous(api, judged_book):
    """``judgements.user_id`` is nullable, and Quepid can attribute them later."""
    response = api.post(_judgements_url(judged_book, user_id=0),
                        json=[_judgement("doc-1", rating=3)], timeout=30)
    assert response.status_code == 200, response.text

    listed = api.get(_judgements_url(judged_book), timeout=10).json()["items"]
    from conftest import fk_id
    assert fk_id(listed[0], "user") is None


def test_judgements_cannot_be_written_under_another_name(api, judged_book, case):
    """They are attributable opinions -- that is why the table is keyed on the rater."""
    from conftest import fk_id

    stranger = fk_id(case, "owner") + 10 ** 6
    response = api.post(_judgements_url(judged_book, user_id=stranger),
                        json=[_judgement("doc-1", rating=3)], timeout=30)
    assert response.status_code == 400, response.text


def test_two_raters_judge_the_same_pair_independently(api, judged_book):
    """The whole point: a human label and a judge's verdict, side by side.

    Written here as the caller and as anonymous, those being the two identities
    this endpoint will write.
    """
    api.post(_judgements_url(judged_book),
             json=[_judgement("doc-1", rating=3)], timeout=30)
    api.post(_judgements_url(judged_book, user_id=0),
             json=[_judgement("doc-1", rating=0)], timeout=30)

    listed = api.get(_judgements_url(judged_book), timeout=10).json()["items"]
    assert sorted(row["rating"] for row in listed) == [0, 3]


def test_a_rater_can_be_listed_on_their_own(api, judged_book):
    api.post(_judgements_url(judged_book),
             json=[_judgement("doc-1", rating=3)], timeout=30)
    api.post(_judgements_url(judged_book, user_id=0),
             json=[_judgement("doc-2", rating=0)], timeout=30)

    anonymous = api.get(_judgements_url(judged_book, user_id=0), timeout=10).json()
    assert [row["rating"] for row in anonymous["items"]] == [0]


def test_one_raters_judgements_can_be_cleared(api, judged_book):
    """Re-opens the book to that rater without discarding anybody else's work."""
    api.post(_judgements_url(judged_book),
             json=[_judgement("doc-1", rating=3)], timeout=30)
    api.post(_judgements_url(judged_book, user_id=0),
             json=[_judgement("doc-2", rating=0)], timeout=30)

    response = api.delete(_judgements_url(judged_book, user_id=0), timeout=10)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 1}

    left = api.get(_judgements_url(judged_book), timeout=10).json()["items"]
    assert [row["rating"] for row in left] == [3]


def test_every_judgement_can_be_cleared(api, judged_book):
    api.post(
        _judgements_url(judged_book),
        json=[_judgement("doc-1", rating=3), _judgement("doc-2", rating=0)],
        timeout=30,
    )

    response = api.delete(_judgements_url(judged_book), timeout=10)
    assert response.json() == {"deleted": 2}
    assert api.get(_judgements_url(judged_book), timeout=10).json()["items"] == []


def test_clearing_judgements_keeps_the_pairs(api, judged_book):
    """Unlike DELETE on query_doc_pairs, the book still knows what to judge."""
    api.post(_judgements_url(judged_book),
             json=[_judgement("doc-1", rating=3)], timeout=30)
    api.delete(_judgements_url(judged_book), timeout=10)

    pairs = api.get(_pairs_url(judged_book), timeout=10).json()["items"]
    assert len(pairs) == 3


def test_judgements_go_when_the_pairs_do(api, judged_book):
    """A judgement hangs off a pair, so clearing the pairs takes them with it."""
    api.post(_judgements_url(judged_book),
             json=[_judgement("doc-1", rating=3)], timeout=30)
    api.delete(_pairs_url(judged_book), timeout=30)

    assert api.get(_judgements_url(judged_book), timeout=10).json()["items"] == []


def test_a_book_with_no_scale_accepts_any_rating(api, book):
    """The scale check only applies when the book has one to check against."""
    api.post(
        _pairs_url(book),
        json=[{"query_text": "farm animals", "doc_id": "doc-1"}],
        timeout=30,
    )
    response = api.post(_judgements_url(book),
                        json=[_judgement("doc-1", rating=17)], timeout=30)
    assert response.status_code == 200, response.text


def test_a_stranger_cannot_load_judgements(member_api, judged_book):
    response = member_api.post(_judgements_url(judged_book),
                               json=[_judgement("doc-1", rating=3)], timeout=30)
    assert response.status_code == 404


def test_a_stranger_cannot_clear_judgements(member_api, judged_book):
    assert member_api.delete(_judgements_url(judged_book), timeout=10).status_code == 404


def test_judgements_on_an_unknown_book_are_404(api):
    url = f"{BASE_URL}/books/{10 ** 9}/judgements/"
    assert api.post(url, json=[_judgement("doc-1")], timeout=10).status_code == 404
