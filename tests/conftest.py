"""Fixtures for the HTTP integration suite.

These tests drive the deployed API over HTTP -- nginx, gunicorn, django-ninja
and a real MySQL -- rather than importing Django. That is deliberate. The whole
risk this project carries is the gap between ``quepid/models.py`` (frozen
``inspectdb`` output) and a Rails-owned schema that keeps migrating underneath
it, and a mocked queryset cannot see that gap: it returns whatever it was told
to return, including columns the database dropped years ago.

.. warning::

   **These tests write to a real Quepid database.** They create teams, scorers,
   search endpoints, cases, queries, ratings and books, and delete them again on
   teardown. Point them at a throwaway Compose stack, never at anything whose
   data you care about. Teardown is best-effort: a crashed run leaves rows
   behind.

Running them::

    docker compose up -d
    export QUEPID_API_TOKEN=$(...)          # thor user:add_api_key
    export QUEPID_TARGET=8.3.6              # the Quepid the stack is running
    pytest

Without ``QUEPID_API_TOKEN`` every test skips, so a bare ``pytest`` is safe.

``QUEPID_TARGET`` is not cosmetic. Quepid v8.4.0 dropped ``books.scorer_id`` and
``books.selection_strategy_id``, which changes both the request this suite has
to send and the response shape it should assert -- see ``tests/test_books.py``
and ``docs/quepid-compatibility.md``. Declaring the version means the suite can
check that the database actually agrees with you.
"""
import os
import uuid
import warnings

import pytest
import requests


BASE_URL = os.getenv("QUEPID_API_URL", "http://localhost:8081/api").rstrip("/")

# Quepid v8.4.0 is the cutover: books lose scorer_id and selection_strategy_id.
BOOKS_SPLIT = (8, 4)


def _version(raw):
    """Parse '8.3.6' into (8, 3, 6). Trailing junk and short forms are fine."""
    parts = []
    for chunk in raw.strip().lstrip("v").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)


TARGET = _version(os.getenv("QUEPID_TARGET", "8.5.0"))

#: True when the connected Quepid still has books.scorer_id and
#: books.selection_strategy_id, i.e. anything before v8.4.0.
LEGACY_BOOKS = TARGET < BOOKS_SPLIT

#: Rails seeds 'Single Rater' first, so it lands on id 1 in a freshly seeded
#: database. Only consulted when LEGACY_BOOKS is true; override if your stack
#: was seeded differently.
SELECTION_STRATEGY_ID = int(os.getenv("QUEPID_SELECTION_STRATEGY_ID", "1"))


def unique(prefix):
    """A name no other run will collide with, so the suite is re-runnable."""
    return f"{prefix}-test-{uuid.uuid4().hex[:8]}"


def fk_id(row, name):
    """Read a foreign key's id out of a response, whichever spelling it used.

    ``quepid/schemas.py`` builds every schema with ``fields = "__all__"``, and
    how django-ninja renders a ForeignKey (``case`` vs ``case_id``, bare id vs
    nested object) is a detail of the library, not of this API. Tests assert on
    the relationship, so they should not break when that detail changes.
    """
    for key in (name, f"{name}_id"):
        if key in row:
            value = row[key]
            return value.get("id") if isinstance(value, dict) else value
    raise AssertionError(f"no {name!r} or {name}_id in response: {sorted(row)}")


@pytest.fixture(scope="session")
def live_stack():
    """Skip the whole suite unless something is answering at BASE_URL.

    Separate from ``api`` so that tests about *unauthenticated* behaviour still
    get the reachability guard without needing a token.
    """
    try:
        requests.get(f"{BASE_URL}/scorers/", timeout=10)
    except requests.RequestException as exc:
        pytest.skip(f"no API at {BASE_URL}: {exc}")
    return BASE_URL


@pytest.fixture(scope="session")
def api(live_stack):
    """An authenticated session against the API.

    The token is a Quepid-issued API key -- the same one the official Quepid API
    accepts. Mint one with ``thor user:add_api_key`` (see CLAUDE.md).
    """
    token = os.getenv("QUEPID_API_TOKEN")
    if not token:
        pytest.skip("QUEPID_API_TOKEN is unset; integration tests need a live stack")

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    probe = session.get(f"{BASE_URL}/scorers/", timeout=10)
    if probe.status_code == 401:
        pytest.fail(f"QUEPID_API_TOKEN rejected by {BASE_URL} -- check the token")
    probe.raise_for_status()

    yield session
    session.close()


def _discard(api, url):
    """Best-effort teardown. A failed delete must not mask a test failure.

    It must not be silent either. An earlier version of this helper ignored the
    response entirely, so 35 cases whose DELETE returned 500 looked like clean
    teardown and the leak was only visible by counting rows in MySQL. Warn
    loudly instead: pytest surfaces warnings in the run summary, and a teardown
    that cannot clean up is worth seeing without failing the test that passed.
    """
    try:
        response = api.delete(url, timeout=10)
    except requests.RequestException as exc:
        warnings.warn(f"teardown DELETE {url} failed: {exc}")
        return

    if response.status_code >= 300:
        warnings.warn(
            f"teardown DELETE {url} -> {response.status_code}: {response.text[:200]}"
        )


def _create(api, url, payload):
    """POST and return the created row, failing loudly with the body on error.

    Every router answers a rejected write with ``400`` and a bare string (the
    house style noted in CLAUDE.md), so surfacing that string is the difference
    between a usable failure and a bare status code.
    """
    response = api.post(url, json=payload, timeout=30)
    if response.status_code != 200:
        pytest.fail(
            f"POST {url} -> {response.status_code}: {response.text}\n"
            f"payload: {payload}"
        )
    return response.json()


@pytest.fixture
def team(api):
    row = _create(api, f"{BASE_URL}/teams/", {"name": unique("team")})
    yield row
    _discard(api, f"{BASE_URL}/teams/{row['id']}/")


@pytest.fixture
def scorer(api):
    row = _create(api, f"{BASE_URL}/scorers/", {"name": unique("scorer")})
    yield row
    _discard(api, f"{BASE_URL}/scorers/{row['id']}/")


@pytest.fixture
def search_endpoint(api):
    """A search endpoint row.

    The URL is never dereferenced. No router in this API makes an outbound
    request -- ``api/toolbox.py`` is the only module that does and it is
    commented out of ``quepid_api/api.py`` -- so an unroutable host is the
    honest fixture here, and it fails loudly if that ever stops being true.
    """
    row = _create(
        api,
        f"{BASE_URL}/search_endpoints/",
        {
            "name": unique("endpoint"),
            "endpoint_url": "http://search.invalid/solr/collection1/select",
            "search_engine": "solr",
            "api_method": "GET",
        },
    )
    yield row
    _discard(api, f"{BASE_URL}/search_endpoints/{row['id']}/")


@pytest.fixture
def case(api, scorer, search_endpoint):
    """A case, plus the try that ``create_case`` writes alongside it.

    Teardown *archives* rather than removes: ``DELETE /case/{id}/`` is a soft
    delete, because Rails owns the cascade off ``cases`` and Django cannot
    reproduce it (see ``api/cases.py:delete_case``). So each run leaves its
    cases behind with ``archived = 1``. Periodically sweep them with::

        DELETE FROM cases WHERE case_name LIKE '%-test-%' AND archived = 1;

    after clearing their tries, queries and ratings -- or just re-create the
    Compose volume.
    """
    row = _create(
        api,
        f"{BASE_URL}/case/",
        {
            "name": unique("case"),
            "scorer_id": scorer["id"],
            "search_endpoint_id": search_endpoint["id"],
            "nightly": 0,
        },
    )
    yield row
    _discard(api, f"{BASE_URL}/case/{row['id']}/")


@pytest.fixture
def query(api, case):
    row = _create(
        api,
        f"{BASE_URL}/query/{case['id']}/",
        {"query_text": "wingback armchair", "query_options": {"fq": "in_stock:true"}},
    )
    yield row
    _discard(api, f"{BASE_URL}/query/{case['id']}/{row['id']}")


@pytest.fixture
def ratings(api, query):
    """Four ratings on synthetic doc ids.

    ``api/ratings.py`` declares ``doc_id: str`` and validates only that the
    *query* exists, so these ids need not resolve to anything in a search index.
    That is what keeps this suite free of Elasticsearch and of any corpus.
    """
    url = f"{BASE_URL}/rating/query/{query['id']}/rating/"
    rows = [
        _create(api, url, {"doc_id": f"doc-{n}", "rating": n % 4})
        for n in range(1, 5)
    ]
    yield rows
    for row in rows:
        _discard(api, f"{url}{row['doc_id']}")


@pytest.fixture
def book_payload(scorer):
    """The create-book body for the declared target version.

    Before v8.4.0 ``scorer_id`` and ``selection_strategy_id`` are required by
    ``CreateBook``; from v8.4.0 the columns behind them no longer exist.
    """
    payload = {"name": unique("book"), "description": "fixture book"}
    if LEGACY_BOOKS:
        payload["scorer_id"] = scorer["id"]
        payload["selection_strategy_id"] = SELECTION_STRATEGY_ID
    return payload


@pytest.fixture
def book(api, book_payload):
    row = _create(api, f"{BASE_URL}/books/", book_payload)
    yield row
    _discard(api, f"{BASE_URL}/books/{row['id']}")
