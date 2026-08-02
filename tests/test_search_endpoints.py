"""Integration tests for /api/search_endpoints.

Two things here matter beyond plain CRUD.

**Nothing dereferences the URL.** No active router in this API makes an outbound
request, so an endpoint row is inert configuration. These tests use an
unroutable host on purpose -- if that ever stops being true they will hang or
fail, which is the signal you want.

**v8.5.0 adds columns but removes none** (``requests_per_minute``,
``test_query``), so this module should pass unchanged across the upgrade. The
one to watch is ``basic_auth_credential``, which 8.6.0-dev encrypts at rest --
see ``test_basic_auth_credential_is_not_writable_here``.
"""
import pytest
import requests

from conftest import BASE_URL, unique


pytestmark = pytest.mark.integration


def _payload(**overrides):
    body = {
        "name": unique("endpoint"),
        "endpoint_url": "http://search.invalid/solr/collection1/select",
        "search_engine": "solr",
        "api_method": "GET",
    }
    body.update(overrides)
    return body


def test_create_search_endpoint(search_endpoint):
    assert isinstance(search_endpoint["id"], int)
    assert search_endpoint["endpoint_url"].startswith("http://search.invalid/")


def test_search_endpoint_shape(search_endpoint):
    assert {
        "id", "name", "search_engine", "endpoint_url",
        "api_method", "archived", "proxy_requests",
    } <= set(search_endpoint)


def test_created_endpoint_is_not_archived(search_endpoint):
    """create_search_endpoint hardcodes archived=0 rather than leaving it null."""
    assert search_endpoint["archived"] == 0


def test_basic_auth_credential_is_not_writable_here(search_endpoint):
    """The credential column is readable but has no way in through this API.

    ``CreateSearchEndpoint`` and ``UpdateSearchEndpoint`` both omit it, yet the
    ``SearchEndpoint`` schema is ``fields = "__all__"``, so it comes back on
    every read. That asymmetry is why Quepid 8.6.0-dev encrypting the column
    (migration ``20260306000002``) would surface ciphertext here rather than
    breaking loudly -- and why the upgrade plan stops at v8.5.0.
    """
    assert "basic_auth_credential" in search_endpoint
    assert search_endpoint["basic_auth_credential"] is None


@pytest.mark.parametrize("engine", ["solr", "es", "opensearch", "searchapi"])
def test_accepted_search_engines(api, engine):
    response = api.post(
        f"{BASE_URL}/search_endpoints/", json=_payload(search_engine=engine), timeout=30
    )
    assert response.status_code == 200, response.text
    api.delete(f"{BASE_URL}/search_endpoints/{response.json()['id']}/", timeout=10)


def test_unknown_search_engine_is_rejected(api):
    """search_engine is a Literal, so ninja rejects it before the handler runs."""
    response = api.post(
        f"{BASE_URL}/search_endpoints/", json=_payload(search_engine="vespa"), timeout=10
    )
    assert response.status_code == 422


def test_get_search_endpoint(api, search_endpoint):
    response = api.get(f"{BASE_URL}/search_endpoints/{search_endpoint['id']}/", timeout=10)
    assert response.status_code == 200
    assert response.json()["id"] == search_endpoint["id"]


def test_get_unknown_search_endpoint_is_404(api):
    response = api.get(f"{BASE_URL}/search_endpoints/999999999/", timeout=10)
    assert response.status_code == 404


def test_list_search_endpoints_is_paginated(api, search_endpoint):
    response = api.get(f"{BASE_URL}/search_endpoints/", timeout=30)
    assert response.status_code == 200
    assert {"items", "count"} <= set(response.json())


def test_update_search_endpoint(api, search_endpoint):
    renamed = unique("endpoint-renamed")
    response = api.put(
        f"{BASE_URL}/search_endpoints/{search_endpoint['id']}/",
        json=_payload(name=renamed, endpoint_url="http://other.invalid/select"),
        timeout=10,
    )
    assert response.status_code == 200, response.text

    updated = response.json()
    assert updated["name"] == renamed
    assert updated["endpoint_url"] == "http://other.invalid/select"


def test_update_clears_mapper_code_when_omitted(api, search_endpoint):
    """``mapper_code`` is assigned unconditionally, unlike every sibling field.

    ``api/search_endpoints.py:82`` does a bare ``endpoint.mapper_code =
    data.mapper_code`` outside the ``if data.x is not None`` guards the other
    fields get. A PUT that omits mapper_code therefore wipes it, while a PUT
    that omits ``name`` leaves the name alone. This test pins that asymmetry so
    it is a deliberate choice rather than an accident; if it is ever made
    consistent, this test is the one to delete.
    """
    endpoint_id = search_endpoint["id"]

    seeded = api.put(
        f"{BASE_URL}/search_endpoints/{endpoint_id}/",
        json=_payload(mapper_code="function map(doc) { return doc; }"),
        timeout=10,
    )
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["mapper_code"] is not None

    cleared = api.put(
        f"{BASE_URL}/search_endpoints/{endpoint_id}/", json=_payload(), timeout=10
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["mapper_code"] is None


def test_update_unknown_search_endpoint_is_404(api):
    response = api.put(
        f"{BASE_URL}/search_endpoints/999999999/", json=_payload(), timeout=10
    )
    assert response.status_code == 404


def test_delete_search_endpoint(api):
    created = api.post(f"{BASE_URL}/search_endpoints/", json=_payload(), timeout=30)
    assert created.status_code == 200, created.text
    endpoint_id = created.json()["id"]

    deleted = api.delete(f"{BASE_URL}/search_endpoints/{endpoint_id}/", timeout=10)
    assert deleted.status_code == 204
    assert api.get(
        f"{BASE_URL}/search_endpoints/{endpoint_id}/", timeout=10
    ).status_code == 404


def test_search_endpoints_require_authentication(live_stack):
    assert requests.get(f"{BASE_URL}/search_endpoints/", timeout=10).status_code == 401
