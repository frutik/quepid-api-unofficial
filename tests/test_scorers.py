"""Integration tests for /api/scorers.

The ``scorers`` table is unchanged between v8.1.0 and v8.5.0, so like teams this
is a control module for the upgrade.

Worth knowing while reading these: ``CreateScorer`` accepts only ``name``, but
the ``Scorer`` schema is ``fields = "__all__"``, so the response carries the
whole row -- ``code``, ``scale``, ``scale_with_labels``, ``communal`` -- all
null on a scorer created through this API. A scorer created here is therefore
not usable for actual scoring in Quepid; that needs ``code``, which this API
has no way to set.
"""
import pytest
import requests

from conftest import BASE_URL, unique


pytestmark = pytest.mark.integration


def test_create_scorer(scorer):
    assert isinstance(scorer["id"], int)
    assert scorer["name"].startswith("scorer-test-")


def test_scorer_shape(scorer):
    assert {"id", "name", "code", "scale", "communal"} <= set(scorer)


def test_created_scorer_has_no_code(scorer):
    """CreateScorer takes only a name, so nothing populates the scoring code."""
    assert scorer["code"] is None


def test_get_scorer(api, scorer):
    response = api.get(f"{BASE_URL}/scorers/{scorer['id']}/", timeout=10)
    assert response.status_code == 200
    assert response.json()["id"] == scorer["id"]


def test_get_unknown_scorer_is_404(api):
    assert api.get(f"{BASE_URL}/scorers/999999999/", timeout=10).status_code == 404


def test_list_scorers_is_paginated(api, scorer):
    response = api.get(f"{BASE_URL}/scorers/", timeout=30)
    assert response.status_code == 200
    assert {"items", "count"} <= set(response.json())


def test_list_scorers_includes_the_seeded_communal_ones(api):
    """Rails seeds nDCG@10, DCG@10, CG@10, P@10 and AP@10 as communal scorers.

    This API does no row scoping at all (see CLAUDE.md), so every token sees
    them. Asserting on the seeds rather than on a fixture also confirms the
    stack was actually seeded -- a bare ``db:migrate`` with no ``db:seed``
    leaves cases uncreatable, since ``CreateCase.scorer_id`` defaults to 5.
    """
    body = api.get(f"{BASE_URL}/scorers/", timeout=30).json()
    names = {row["name"] for row in body["items"]}
    assert names & {"nDCG@10", "AP@10"}, (
        f"no seeded scorers found ({sorted(names)[:10]}); run bin/rake db:seed"
    )


def test_update_scorer(api, scorer):
    renamed = unique("scorer-renamed")
    response = api.put(
        f"{BASE_URL}/scorers/{scorer['id']}/", json={"name": renamed}, timeout=10
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == renamed


def test_update_unknown_scorer_is_404(api):
    response = api.put(
        f"{BASE_URL}/scorers/999999999/", json={"name": "nope"}, timeout=10
    )
    assert response.status_code == 404


def test_delete_scorer(api):
    created = api.post(
        f"{BASE_URL}/scorers/", json={"name": unique("scorer")}, timeout=30
    )
    assert created.status_code == 200, created.text
    scorer_id = created.json()["id"]

    assert api.delete(f"{BASE_URL}/scorers/{scorer_id}/", timeout=10).status_code == 204
    assert api.get(f"{BASE_URL}/scorers/{scorer_id}/", timeout=10).status_code == 404


def test_scorers_require_authentication(live_stack):
    assert requests.get(f"{BASE_URL}/scorers/", timeout=10).status_code == 401
