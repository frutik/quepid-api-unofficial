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

Bumping this to **0.9.0** rather than a patch: this release **re-targets Quepid
from v8.0.0 – v8.3.7 to v8.4.0 – v8.5.0**, which is a breaking change to both the
databases it runs against and this API's own books contract. `DELETE
/api/case/{id}/` and `GET /api/case/` also change behaviour in ways a caller can
observe.

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
- **27 integration tests for the MCP server** (`tests/test_mcp.py`), the first
  coverage that surface has ever had — the REST suite never calls `/mcp/mcp`.
  They run over a small JSON-RPC client (`tests/mcp_client.py`) that speaks the
  streamable-HTTP transport directly, and are organised around the three prompts
  in the demo video linked from the README: listing cases with their try counts,
  nightly flags and books; resolving a case **by name** and paging its queries;
  and reading the query DSL off a case's latest try. Alongside those, guards for
  what the Quepid 8.5.0 move changed here — `selectionstrategies` unpublished,
  the dropped `books` columns, the `CompositePrimaryKey` junction tables, and
  `$match` traversal through `Tries.search_endpoint`, which is the cheapest way
  to catch a regeneration silently reverting that hand-patched ForeignKey.
- `QUEPID_MEMBER_API_TOKEN` (optional) enables the three MCP row-scoping tests.
  They need a **non-administrator** key: `quepid_mcp/mcp.py:119` bypasses
  scoping for admins, so asserting it with the bootstrap token would pass
  whether or not scoping works. Unset, they skip.
- `npm test`, `npm run test:books` and `npm run test:mcp`; `pytest.ini`;
  `requests` in `quepid_api/requirements.txt`.
- `GET /api/case/` accepts **`?archived=true`** to list archived cases instead of
  active ones.

### Changed

- **Quepid support moves to v8.4.0 – v8.5.0; v8.3.7 and older are no longer
  supported.** `quepid/models.py` has been regenerated from a v8.5.0 database
  (`schema.rb` `2026_01_14_150154`), the dev stack and the `quepid/` submodule
  now both pin **8.5.0**, and for the first time all three agree. The range does
  not span the v8.4.0 cutover in either direction: those migrations both dropped
  and added `books` columns, so no single `inspectdb` output satisfies v8.3.x and
  v8.4.0+ at once. See
  [`docs/quepid-compatibility.md`](docs/quepid-compatibility.md).
- **`POST /api/books` and `PATCH /api/books/{id}` no longer accept `scorer_id` or
  `selection_strategy_id`.** Quepid v8.4.0 dropped both columns and the
  `selection_strategies` table. `scorer_id` and `selection_strategy_id` were
  *required* by `CreateBook`, so every existing caller must drop them. Books are
  now graded through `scale` / `scale_with_labels`, which this API does not yet
  expose.
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

### Removed

- **The MCP `selectionstrategies` collection**, leaving 13. The table no longer
  exists in Quepid v8.4.0+. `books.selection_strategy` is gone from the `books`
  collection's advertised fields and from the server instructions, which now
  describe `scale` / `scale_with_labels` instead.

### Fixed

- **`query_options` was double-encoded on write.** `queries.options` became a
  MySQL `json` column in Quepid v8.2.0 and now reflects as a `JSONField`, so
  `api/queries.py` calling `json.dumps(...)` made Django serialize an
  already-serialized string — the column ended up holding a JSON *string* where
  Quepid expects an object. Both write sites now pass the dict through. This was
  invisible over REST (`resolve_query_options` falls back to `json.loads` and
  recovers), but broke Quepid's own reads and the MCP `queries` collection, which
  has no resolver in front of it. Verify with
  `SELECT JSON_TYPE(options) FROM queries` — it should say `OBJECT`.
- **`POST /api/books` failed with `Column 'archived' cannot be null`.**
  `books.archived` is `NOT NULL` with a Rails-side default, and `inspectdb` gives
  it no Django default, so Django sent `NULL`. `create_book` now passes
  `archived=0`, the same way it already had to for `created_at` / `updated_at`.
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
- ~~The `query_options` double-encoding is not covered by a test.~~ Now covered,
  but only from MCP (`test_query_options_is_an_object_not_a_double_encoded_string`),
  which returns `queryset.values()` with no resolver in front of it. Verified by
  reintroducing the bug: the MCP test fails while all 16 REST query tests still
  pass, which is the point — `resolve_query_options` recovers via `json.loads`,
  so no REST assertion can ever see it.
- Books' `scale`, `scale_with_labels` and `scoring_guidelines` — which replaced
  the dropped scorer and selection-strategy references in v8.4.0 — are readable
  through `GET /api/books` but cannot be set: `CreateBook` and `UpdateBook` do
  not expose them.
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
