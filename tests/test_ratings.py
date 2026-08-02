"""Integration tests for /api/rating.

Ratings are where this suite earns its independence from a search engine.
``CreateRating`` declares ``doc_id: str`` and ``create_rating`` validates only
that the *query* exists -- nothing resolves the document, in this API or in the
database. So ``doc-1`` is as valid a rating target as a real product id, which
is why none of these tests need Elasticsearch, a corpus, or WANDS.

The route is doubly nested and repeats the word: ``/api/rating/query/{query_id}
/rating/``. That is the mount point (``/rating``) plus the router's own path
(``/query/{query_id}/rating/``), not a typo.
"""
import pytest
import requests

from conftest import BASE_URL, fk_id


pytestmark = pytest.mark.integration


def _url(query_id):
    return f"{BASE_URL}/rating/query/{query_id}/rating/"


def test_create_ratings(ratings):
    assert len(ratings) == 4
    assert {row["doc_id"] for row in ratings} == {"doc-1", "doc-2", "doc-3", "doc-4"}


def test_rating_shape(ratings):
    assert {"id", "doc_id", "rating", "user_id"} <= set(ratings[0])


def test_rating_is_a_float(ratings):
    """``Ratings.rating`` is a FloatField, so integers come back as 1.0 not 1.

    Worth pinning: Quepid's scorers work in integer scales (0..3 for nDCG@10,
    0..1 for AP@10), so it is easy to assume the API round-trips ints.
    """
    assert all(isinstance(row["rating"], float) for row in ratings)


def test_arbitrary_doc_ids_are_accepted(api, query):
    """No validation, no existence check -- the property this suite relies on."""
    url = _url(query["id"])
    created = api.post(
        url, json={"doc_id": "not-a-real-document-anywhere", "rating": 3}, timeout=30
    )
    assert created.status_code == 200, created.text
    try:
        assert created.json()["doc_id"] == "not-a-real-document-anywhere"
    finally:
        api.delete(f"{url}not-a-real-document-anywhere", timeout=10)


def test_rating_belongs_to_its_query(ratings, query):
    assert fk_id(ratings[0], "query") == query["id"]


def test_rating_has_no_user(ratings):
    """``Ratings.user_id`` is a plain IntegerField and create_rating never sets it.

    Quepid attributes ratings to a user; this API does not, even though it knows
    who the caller is via ``request.auth``. Anything reading ratings by rater
    will see NULL for every row this API wrote.
    """
    assert all(row["user_id"] is None for row in ratings)


def test_create_rating_on_unknown_query_is_400(api):
    response = api.post(_url(999999999), json={"doc_id": "doc-1", "rating": 1}, timeout=30)
    assert response.status_code == 400
    assert "Unknown query" in response.text


def test_list_ratings_is_paginated(api, query, ratings):
    response = api.get(_url(query["id"]), timeout=30)
    assert response.status_code == 200

    body = response.json()
    assert {"items", "count"} <= set(body)
    assert {row["doc_id"] for row in body["items"]} >= {"doc-1", "doc-4"}


def test_list_ratings_is_scoped_to_the_query(api, case, ratings):
    """view_ratings filters on query_id, so a sibling query sees none of these."""
    other = api.post(
        f"{BASE_URL}/query/{case['id']}/", json={"query_text": "sibling"}, timeout=30
    )
    assert other.status_code == 200, other.text
    other_id = other.json()["id"]

    try:
        body = api.get(_url(other_id), timeout=30).json()
        assert body["items"] == []
    finally:
        api.delete(f"{BASE_URL}/query/{case['id']}/{other_id}", timeout=10)


def test_delete_rating_by_doc_id(api, query):
    """Ratings are addressed by doc_id, not by their own primary key."""
    url = _url(query["id"])
    created = api.post(url, json={"doc_id": "doc-doomed", "rating": 2}, timeout=30)
    assert created.status_code == 200, created.text

    deleted = api.delete(f"{url}doc-doomed", timeout=10)
    assert deleted.status_code == 200
    assert deleted.json() == {"message": "Rating deleted successfully"}

    remaining = api.get(url, timeout=30).json()
    assert "doc-doomed" not in {row["doc_id"] for row in remaining["items"]}


def test_delete_unknown_rating_is_404(api, query):
    response = api.delete(f"{_url(query['id'])}never-rated", timeout=10)
    assert response.status_code == 404


def test_ratings_require_authentication(live_stack):
    assert requests.get(_url(1), timeout=10).status_code == 401
