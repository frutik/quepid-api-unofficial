"""Integration tests for /api/teams.

Teams are unaffected by the v8.1.0 -> v8.5.0 schema move (the ``teams`` table is
byte-identical across both), so this module is a straight CRUD contract check.
Its value in the upgrade is as a control: if teams break too, the problem is the
regeneration itself, not the books-specific migrations.
"""
import pytest
import requests

from conftest import BASE_URL, unique


pytestmark = pytest.mark.integration


def test_create_team(team):
    assert isinstance(team["id"], int)
    assert team["name"].startswith("team-test-")


def test_team_shape(team):
    assert {"id", "name", "created_at", "updated_at"} <= set(team)


def test_get_team(api, team):
    response = api.get(f"{BASE_URL}/teams/{team['id']}/", timeout=10)
    assert response.status_code == 200
    assert response.json()["id"] == team["id"]


def test_get_unknown_team_is_404(api):
    assert api.get(f"{BASE_URL}/teams/999999999/", timeout=10).status_code == 404


def test_list_teams_is_paginated(api, team):
    response = api.get(f"{BASE_URL}/teams/", timeout=30)
    assert response.status_code == 200
    assert {"items", "count"} <= set(response.json())


def test_update_team(api, team):
    renamed = unique("team-renamed")
    response = api.put(
        f"{BASE_URL}/teams/{team['id']}/", json={"name": renamed}, timeout=10
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == renamed


def test_update_unknown_team_is_404(api):
    response = api.put(
        f"{BASE_URL}/teams/999999999/", json={"name": "nope"}, timeout=10
    )
    assert response.status_code == 404


def test_delete_team(api):
    created = api.post(f"{BASE_URL}/teams/", json={"name": unique("team")}, timeout=30)
    assert created.status_code == 200, created.text
    team_id = created.json()["id"]

    # delete_team returns 204, unlike delete_book which returns 200 + a message.
    assert api.delete(f"{BASE_URL}/teams/{team_id}/", timeout=10).status_code == 204
    assert api.get(f"{BASE_URL}/teams/{team_id}/", timeout=10).status_code == 404


def test_delete_unknown_team_is_404(api):
    assert api.delete(f"{BASE_URL}/teams/999999999/", timeout=10).status_code == 404


def test_teams_require_authentication(live_stack):
    assert requests.get(f"{BASE_URL}/teams/", timeout=10).status_code == 401
