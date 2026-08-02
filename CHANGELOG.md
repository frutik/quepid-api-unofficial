# Changelog

All notable changes to this project are recorded here, newest first. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## How to maintain this file

**Add your entry to `[Unreleased]` in the same commit as the change.** Not
afterwards, not at release time — the context you need to write a useful line is
in your head while you are making the change, and gone a week later.

- Group under the standard headings: **Added**, **Changed**, **Deprecated**,
  **Removed**, **Fixed**, **Security**. Drop any heading you have nothing for.
- Write for someone deciding whether an upgrade affects them, not for someone
  reading the diff. Say what changed about the *behaviour* and, when it is not
  obvious, why.
- Call out anything that changes this API's own contract — a response shape, a
  status code, a default — since consumers have no other warning.
- Anything that changes which **Quepid** versions this code runs against belongs
  here *and* in [`docs/quepid-compatibility.md`](docs/quepid-compatibility.md),
  which is the detailed version matrix.

On release: rename `[Unreleased]` to the new version with today's date, set the
same version in `package.json` (the source of truth), and push a `v*` tag —
which is what triggers the Docker build in
`.github/workflows/docker-image.yml`.

---

## [Unreleased]

Bumping this to **0.9.0** rather than a patch: `DELETE /api/case/{id}/` and
`GET /api/case/` both change behaviour in ways a caller can observe.

### Added

- **The project's first tests.** `tests/` holds 97 integration tests that drive
  the deployed API over HTTP — nginx, gunicorn, django-ninja and a real MySQL —
  rather than importing Django. Every model is `managed = False`, so
  pytest-django cannot build a test database, and mocking the ORM would hide the
  one class of bug that matters here: `quepid/models.py` is frozen `inspectdb`
  output over a Rails-owned schema that keeps migrating underneath it, and a
  mock returns whatever it was told to, including columns the database dropped.
  There is deliberately no `DJANGO_SETTINGS_MODULE` and no pytest-django.
- Fixtures need **no search engine and no corpus** — ten synthetic rows. Nothing
  in this API dereferences a document: `create_rating` validates only that the
  query exists, and no active router makes an outbound request.
- `QUEPID_TARGET` env var declares which Quepid the stack runs. It gates the
  books create payload and shape assertions across the v8.4.0 cutover where
  `books.scorer_id` and `books.selection_strategy_id` were dropped, and asserts
  in both directions — so it also catches a target declared newer than the
  database actually is.
- `npm test` and `npm run test:books`; `pytest.ini`; `requests` in
  `quepid_api/requirements.txt`.
- `GET /api/case/` accepts **`?archived=true`** to list archived cases instead of
  active ones.

### Changed

- **`DELETE /api/case/{id}/` now archives instead of deleting.** Still `204`, and
  reversible with `PUT {"archived": 0}`. A hard delete was never actually
  possible: `create_case` always writes a try, `tries.case_id` carries a real FK
  constraint, and `inspectdb` reflects every relation as `DO_NOTHING`, so Django
  emitted no cascade and MySQL answered `IntegrityError 1451`. The cascade lives
  in Rails (`dependent: :destroy` in `app/models/case.rb`), where the reflection
  cannot see it. Archiving is what Quepid's own UI does.
- **`GET /api/case/` now hides archived cases by default.** Without this, every
  case ever "deleted" through the API would stay in the list. The filter
  *excludes 1* rather than filtering on 0, because `cases.archived` is nullable
  with no default in Rails — a case Quepid wrote itself can be `NULL`, and
  `NULL` still means "not archived".

### Fixed

- **`POST /api/books` always failed.** `create_book` passed `owner_id=request.auth`
  — a `Users` instance — into a plain `IntegerField`, which `int()` cannot adapt,
  so it raised and the router's broad `except Exception` turned it into a `400`.
  `Books.owner_id` only looks like a foreign key; `Cases.owner` and
  `SearchEndpoints.owner` are real ones and were already correct. No notebook had
  ever called `/api/books`, so nothing caught it.

### Known gaps

- `archived = NULL` is unreachable over HTTP (`update_case` treats `None` as
  "leave alone"), so that third state is verified by reading the queryset, not by
  a test.
- The v8.2.0 `queries.options` json drift cannot be detected from REST:
  `resolve_query_options` falls back to `json.loads`, silently recovering from
  double-encoded values. Verifying it needs the stored column or the MCP surface.
- `DELETE` being a soft delete means the test suite leaves archived cases behind
  each run; fixtures cannot do better through the API alone.

---

## [0.8.2] — 2026-08-01

### Fixed

- Gunicorn now binds `8001` by default instead of `8000`, matching the port
  nginx proxies to and the container's exposed port.

## [0.8.1] — 2026-08-01

### Added

- [`docs/quepid-compatibility.md`](docs/quepid-compatibility.md) — the version
  matrix: which Quepid releases this API runs against, how the `models.py`
  baseline was dated, and what breaks in Quepid v8.4.0.
- `quepid_api/quepid_api/gunicorn.py`, making worker count, max requests and
  jitter configurable by environment.

### Removed

- `docs/mcp-server-playbook.md`, the project-agnostic twin of
  `docs/mcp-server-plan.md`.

## [0.8.0] — 2026-08-01

### Added

- **A read-only MCP server** over the same models and the same bearer tokens,
  served at `/mcp/mcp`. 14 collections queried with a MongoDB-style aggregation
  pipeline. Unlike the ninja routers, every toolset scopes rows to the token
  owner and their teams; Quepid administrators bypass it.
- `quepid_api/common/auth.py` — the bearer-token to `Users` lookup, extracted so
  the ninja API and the MCP server share it without either depending on the
  other.
- The upstream Rails app as a git submodule at `quepid/`, reference only, so the
  schema and models this project mirrors can be read rather than guessed at.
- `CLAUDE.md`, `docs/mcp-server-plan.md`, `.mcp.json`, and a Snyk security
  workflow.

### Removed

- `quepid_api/mcp/`. App directories sit directly on `sys.path`, so an app named
  `mcp` would shadow the `mcp` SDK process-wide and break `from mcp.server
  import FastMCP` at startup. The app is `quepid_mcp`.

---

Releases before 0.8.0 predate this file. Their commit messages are mostly `wip`,
so the useful history is in `docs/quepid-compatibility.md`, which reconstructs
which Quepid version each era of tags targeted and why.
