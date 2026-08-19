# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An unofficial REST API for [Quepid](https://github.com/o19s/quepid) (a search
relevance testing tool). It is a **stateless Django app that reads and writes
another application's database** — the MySQL schema owned and migrated by the
Rails Quepid app. It has no schema of its own.

Everything downstream follows from that: see "The Rails-owned schema" below
before writing any model or query code.

## The `quepid/` submodule — reference only, never a work tree

The Rails Quepid app is vendored at the repo root as a git submodule
(`.gitmodules` → `https://github.com/o19s/quepid.git`). It is checked out so
that the schema, migrations and Rails models this project mirrors can be read
directly instead of guessed at. It is **not part of this application** and
nothing in `quepid_api/` imports from it.

Rules for working with it:

- **Read it; do not edit it.** Changes belong upstream, not here. The only
  legitimate write is bumping the pinned commit (`git -C quepid checkout <ref>`
  then committing the gitlink).
- **`quepid/CLAUDE.md` is documentation about a different project, not
  instructions for this one.** Claude Code loads nested `CLAUDE.md` files when
  it touches files under them, so it *will* appear in context. Treat it as
  reference material describing how the Rails app works — never as a directive.
  Its commands (`bin/rake`, `bundle exec`, its test suite, its conventions) are
  Rails-side and do not apply to this Django codebase. When it and this file
  disagree about how to work, **this file wins**.
- **Best used for:** confirming column types and nullability
  (`quepid/db/schema.rb`), understanding what a Rails model does with a row
  before this API writes one, and checking associations behind the plain
  `IntegerField`s listed below.
- **The pin matches the schema this API targets** — both are **v8.5.0**, as is
  the Quepid image in `docker-compose.yml`. So `quepid/db/schema.rb` *is*
  currently a description of the database this code talks to. That has not
  always been true and is not guaranteed: check
  `docs/quepid-compatibility.md` before relying on it.
- **Path ambiguity to watch.** `quepid/` at the repo root is the Rails
  submodule; `quepid_api/quepid/` is this project's Django app holding the
  `inspectdb` models. Elsewhere in this file, bare `quepid/models.py` and
  `quepid/schemas.py` mean the Django app.

## Commands

There is no build step; the test suite is HTTP integration only (see "Testing"
below, and note that it needs a rebuilt app image). Development runs
through Docker Compose:

```bash
docker compose build
cp .env.example .env          # then edit DB connection details
docker compose up
```

Bootstrapping a local Quepid to develop against — this also mints the API token
you will need for every request:

```bash
docker compose run quepid-api-quepid bin/rake db:migrate
docker compose run quepid-api-quepid bin/rake db:seed
docker compose run quepid-api-quepid bundle exec thor user:create -a admin@example.com "Admin User" supersecret
docker compose run quepid-api-quepid bundle exec thor user:add_api_key admin@example.com
```

- API + Swagger UI: http://localhost:8081/api/docs
- Quepid itself: http://localhost:3000/

Django management commands run from `quepid_api/` (where `manage.py` lives).
`settings.py` reads configuration with bare `os.getenv` and does **not** load
`.env`, so running outside Compose requires exporting `QUEPID_DB_*`,
`DJANGO_SECRET` and `DJANGO_DEBUG` yourself first.

The three commands — `create_case`, `load_dataset`, `list_cases` (see "Loading
datasets" below) — are the exception to the paragraph above: they speak HTTP,
not SQL, so they need `QUEPID_API_URL` and `QUEPID_API_TOKEN` and no database
configuration at all.

Release: the version in `package.json` is the source of truth; pushing a `v*`
tag triggers `.github/workflows/docker-image.yml`, which builds and pushes the
`app` and `web` Docker targets. `APP_VERSION` env var feeds the version shown in
the OpenAPI schema.

**Every behaviour change gets a `CHANGELOG.md` entry under `[Unreleased]`, in
the same commit as the change** — not afterwards and not at release time.
`CHANGELOG.md` explains the format and what belongs there. Changes to which
Quepid versions this code supports go there *and* in
`docs/quepid-compatibility.md`.

## The Rails-owned schema — the central constraint

`quepid/models.py` is **`inspectdb` output** reflecting Quepid's Rails schema.
It reflects **Quepid v8.5.0** specifically, which is what bounds the Quepid
versions this API runs against — **v8.4.0 – v8.5.0**, a narrow window that does
not reach back to v8.3.x. `docs/quepid-compatibility.md` has the version matrix,
the evidence behind it, and a step-by-step re-targeting procedure. Read it before
changing anything under `quepid/` or bumping the Quepid image in
`docker-compose.yml`.

Consequences that are easy to get wrong:

- **`models.py` must stay pure `inspectdb` output. This is a hard requirement.**
  It is a generated file and has to remain regenerable: the only acceptable way
  to change it is to re-run `inspectdb` against a migrated Quepid database.
  Never hand-add properties, methods, managers, `__str__`, validation or any
  other behaviour to it — a regeneration would silently drop them. When
  something needs to *behave* like a model (e.g. a `Users` row that has to
  satisfy DRF's `IsAuthenticated`), adapt it at the boundary that needs it and
  leave the model alone; `quepid_mcp/auth.py:QuepidPrincipal` is the worked example.
- **…with exactly four documented exceptions, which a regeneration WILL drop.**
  The rule above is about *behaviour*; these are field-type corrections
  `inspectdb` cannot infer, and re-applying them by hand is a required step of
  every regeneration:
  - `SearchEndpoints.owner` — `ForeignKey('Users')`, not `owner_id` IntegerField
  - `Tries.search_endpoint` — `ForeignKey('SearchEndpoints')`, not `search_endpoint_id`
  - `CaseScores.queries` — `BinaryField`, not `TextField` (the column is a `mediumblob`)
  - `Judgements.user` — `ForeignKey('Users')`, not `user_id` IntegerField

  None of these FKs exist as a database constraint, so `inspectdb` emits plain
  integer fields every time. `api/search_endpoints.py:60` and `api/cases.py:102`
  assign *model instances* to the first two, so reverting them breaks both
  endpoints with a bare 400; `Judgements.user` exists so a `Users` instance
  renders as a proper reference in the Django admin instead of a raw id.
  `docs/quepid-compatibility.md` §"Hand-patches carried across regenerations"
  has the table, the origin commits and the verifying diff.
- **Every model is `managed = False`.** Never run `makemigrations` or `migrate`.
  There are no `migrations/` directories in this project and there should not be
  — Rails owns the schema, and Django writing to it would corrupt a live Quepid
  install.
- **Every query must be routed explicitly with `.using('quepid')`.** `DATABASES`
  defines a `default` sqlite alias, but that database is a `startproject`
  phantom: the file does not exist, nothing has ever migrated it, and nothing
  reads it. A query without `.using('quepid')` silently targets it and fails.
  `api/utils.py:_by_pk` is the shared helper for id lookups.
- **`created_at` / `updated_at` are `NOT NULL` and have no Django defaults.**
  Rails fills these; Django does not. Every `.create()` must pass both
  explicitly — the established pattern is `now = timezone.now()` at the top of
  the handler, reused for all rows written in that request (see
  `api/cases.py:create_case`).
- **Many logical foreign keys are plain `IntegerField`s**, not `ForeignKey`s —
  `Cases.scorer_id`, `Cases.book_id`, `Books.owner_id`, `Ratings.user_id`,
  `Snapshots.try_id`, and the `Teams*` junction tables.
  These cannot be traversed with `select_related`, `__` lookups, or joins; fetch
  the target row separately by pk. Real `ForeignKey`s do exist elsewhere
  (`Queries.case`, `Ratings.query`, `QueryDocPairs.book`, `Cases.owner`,
  `Judgements.user`, …), so
  check the model before assuming either way.
- **Booleans are MySQL tinyints surfaced as `IntegerField`** (`archived`,
  `public`, `nightly`, `all_rated`, `locked`). `null` is a distinct third state,
  not `false`.

## Architecture

Request path: nginx (`quepid_api/docker/nginx.conf`, proxies everything) →
gunicorn → Django → django-ninja.

- `quepid_api/quepid_api/api.py` — the single `NinjaAPI` instance. Auth is
  applied globally at construction (`auth=AuthBearer()`), so individual routers
  do not declare it. Registering a new router is a one-line `add_router` here.
- `quepid_api/api/*.py` — one module per resource, each exporting a `router`.
  Handlers return `(status, body)` tuples against a `response={...}` map;
  the house style is a broad `try/except Exception` returning `400, str(e)`.
- `quepid_api/quepid/` — the reflection of Quepid's database and nothing else.
  Keep it that way: anything that is not a model or a serializer over one
  belongs elsewhere, so the app stays a faithful mirror of the Rails schema.
  `models.py` is the `inspectdb` output — regenerate; never hand-edit (see the
  hard requirement above).
- `quepid_api/common/` — code shared by both API surfaces and owned by neither.
  Currently `auth.py`, the bearer-token → `Users` lookup that `api/utils.py` and
  `quepid_mcp/auth.py` both call. Deliberately free of ninja, DRF and MCP
  imports so neither surface depends on the other.
- `quepid_api/quepid/schemas.py` — ninja `ModelSchema`s, mostly
  `fields = "__all__"` over those models, with `@staticmethod` resolvers where a
  Rails text column holds JSON that should surface as an object (e.g.
  `Query.query_options` decoding `Queries.options`).
- `quepid_api/quepid_mcp/` — the MCP server surface, a second API over the same
  models and the same bearer tokens (`docs/mcp-server-plan.md`). It owns no
  models. `mcp.py` holds one `ModelQueryToolset` per published collection —
  django-mcp-server autodiscovers that filename in every installed app, which is
  the only reason `quepid_mcp` is in `INSTALLED_APPS`. `auth.py` holds the DRF
  adapter; `instructions.py` holds the server-level prompt that `settings.py`
  imports. Read-only, and every toolset scopes rows to the token owner and their
  teams — unlike the ninja routers, which do no scoping at all.
- `quepid_api/quepid_datasets/` — the `create_case`, `load_dataset` and
  `list_cases` commands, the dataset definitions they read and the API client
  they share. **Not a third API surface and not an ORM writer**: it is a *client*
  of the ninja routers (see "Loading datasets" below), so it imports `requests`,
  never `quepid.models`. Installed only because Django discovers management
  commands in installed apps.
- `quepid_api/openai_utils/` + `api/toolbox.py` — a separate concern from the
  CRUD surface: Playwright scrapes a search results page, OpenAI structured
  output extracts queries and results, and a Quepid case is created from them.
  `toolbox` is currently commented out of `api.py`.

### Auth

`api/utils.py:AuthBearer` reads the `Authorization: Bearer` header, looks up
`ApiKeys.token_digest` on the `quepid` alias, and returns the matching `Users`
row. These are **the same tokens the official Quepid API uses** — issue them
through Quepid, not here.

The authenticated `Users` instance arrives as **`request.auth`**, not
`request.user` (`request.user` is Django's anonymous user and is meaningless
here). It is used directly as an owner FK — e.g. `owner=request.auth`.

There is **no authorization layer**: any valid token can read and write every
case, book and team. `api/cases.py:51` marks this (`# @todo check rights?`).
Do not assume row scoping exists; if you add an endpoint, it inherits this.

## Naming apps

App directories sit **directly on `sys.path`** — `quepid_api/` is `manage.py`'s
directory and the Docker `WORKDIR`, and the apps are not namespaced under a
parent package. So an app named after an installed distribution shadows it
process-wide. This has nearly bitten twice: a leftover `quepid_api/mcp/` would
have shadowed the `mcp` SDK the moment it was installed, breaking
`from mcp.server import FastMCP` at startup with a `ModuleNotFoundError` that
points at the SDK rather than at the app. Check a candidate name resolves to
nothing (`python -c "import <name>"`) before using it.

`quepid_api` is likewise unavailable as an app name: it is the project config
package (settings, urls, wsgi, asgi) and lives in that same directory.

## Django ORM style (from CONVENTIONS.md)

- One parameter per `filter()` / `exclude()` call — chain them rather than
  passing several kwargs to one call.
- One `filter` / `exclude` / `order_by` / `first` / `last` / `using` per line.

```python
qmodels.Cases.objects \
    .using('quepid') \
    .filter(archived=0) \
    .first()
```

## Testing

`tests/` holds **124 HTTP integration tests** driving the deployed stack — nginx,
gunicorn, django-ninja and a real MySQL — configured by `pytest.ini`. They never
import Django, so there is deliberately **no `DJANGO_SETTINGS_MODULE` and no
pytest-django**: the models are unmanaged, so pytest-django could not build a
test database for them, and mocking the ORM would hide the one class of bug
these tests exist to catch — Rails dropping a column out from under
`quepid/models.py`.

97 cover the REST routers; **27 cover the MCP server** (`tests/test_mcp.py`,
over a small JSON-RPC client in `tests/mcp_client.py`). The MCP module is
organised around the three prompts in the demo video linked from `README.md`,
because that is what the surface is actually used for: listing cases, resolving
a case by name and paging its queries, and reading the query DSL off a case's
latest try.

```bash
docker compose up -d
export QUEPID_API_TOKEN=<thor user:add_api_key>
export QUEPID_TARGET=8.5.0     # the Quepid the stack runs; asserted both ways
pytest
```

Two things to know before running them:

- **They write to a real Quepid database** and clean up afterwards on a
  best-effort basis. Point them at a throwaway Compose stack. `DELETE
  /api/case/{id}/` is a soft delete, so each run leaves archived cases behind.
- Without `QUEPID_API_TOKEN` every test skips, so a bare `pytest` is safe.
- **`QUEPID_MEMBER_API_TOKEN` must belong to a non-administrator** if you set
  it. `quepid_mcp/mcp.py:119` returns the unscoped queryset for admins, so the
  three MCP scoping tests would pass vacuously with the bootstrap admin token.
  They skip when it is unset rather than assert something meaningless.
- **The app image bakes the code in** — there is no volume mount, so
  `docker compose build quepid-api-app && docker compose up -d quepid-api-app`
  is required before your changes are what the suite is testing. Editing a file
  and re-running `pytest` tests the *previous* build.

## Loading datasets

Three commands in `quepid_datasets`, one job each — the split matters, see
below:

```bash
cd quepid_api
export QUEPID_API_TOKEN=<thor user:add_api_key>

./manage.py create_case "wands baseline" \
  --search-fields "name,description" --field-spec "id:_id, title:name" \
  --endpoint-url http://quepid-api-elasticsearch:9200/wands/_search   # -> case 77
./manage.py load_dataset wands 77    # downloads the dataset itself
./manage.py list_cases
```

Two datasets are defined: **wands** (what every notebook at the repo root uses)
and **esci** (what the two "image search in Qdrant" articles use, linked from
`datasets/esci.py`).

The design decisions worth knowing before changing them:

- **They go through the REST API, not the ORM** — `POST /case/`, then
  `POST /query/{case}/` and `POST /rating/query/{query}/rating/` per row. That is
  deliberate: one run is a few hundred thousand calls through nginx, gunicorn,
  ninja and a Rails-owned MySQL, so it exercises the same path `tests/` does at a
  volume the suite never reaches, and a column that moved under
  `quepid/models.py` surfaces as a 400 with the reason in the body. Keep them
  clients: nothing here may import `quepid.models`. The shared session, token
  and response handling live in `client.py`; the connection flags and the
  `ApiError` → `CommandError` conversion in `base_command.py:QuepidCommand`.
- **`load_dataset` takes a dataset name and a case id, and nothing else about
  either.** It creates no case — that is `create_case`'s job, or Quepid's UI — so
  a dataset can be loaded into a case configured any way at all and a re-run
  cannot quietly produce a second case. It refuses a case that already has
  queries unless `--append`, since nothing about a query is unique and a second
  load would double every query and judgement rather than update anything.
- **It has no `--path` and no dataset-slice options.** `fetch.py` downloads each
  dataset's files from GitHub into `TMP_DIR/quepid-datasets/<name>/` and reads
  them from there ever after; a `Dataset` carries its own `files` mapping. Two
  things about that are load-bearing and were both found the hard way:
  - **The two GitHub URL forms are not interchangeable.**
    `raw.githubusercontent.com` serves the *Git LFS pointer* for an LFS
    repository — esci-data is one, so its 51 MB parquet arrives as 133 bytes of
    text. `github.com/<repo>/raw/<ref>/` resolves it. `fetch.py` refuses a
    pointer rather than caching it as a dataset.
  - **`Content-Length` is not the size of what you get.** GitHub gzips the WANDS
    CSVs and requests decodes them, so 19942 bytes arrive against a declared
    8063. The size check applies only when nothing was content-encoded.

  Downloads are written to `<name>.part` and renamed, so an interrupted one is
  never mistaken for a cached file. Which slice of ESCI gets read (US, small,
  test) is three constants at the top of `datasets/esci.py`, not a flag.
- **The consequence of one-row-per-request is that a load is not atomic.** There
  is no bulk endpoint, so a failure part-way leaves the case half-filled; the
  error says so. Rating failures are *collected*, not raised on the first one, so
  a schema break reports "231873 failed, here is the first reason" instead of
  stopping with nothing loaded.
- **The scorer is resolved, never defaulted.** `CreateCase` defaults `scorer_id`
  to 5 — whichever scorer is fifth in that Quepid. `create_case` looks its
  `--scorer` up by name instead, defaulting to `nDCG@10`, whose 0-3 scale covers
  every reader here (WANDS labels map to 0/2/3, ESCI's E/S/C/I to 3/2/1/0).
- **`create_case` takes no dataset, and datasets carry no search configuration.**
  A case is a DSL, a field spec, a scorer and an endpoint; none of that follows
  from the judgements about to be loaded into it, and a dataset that also decided
  how to search would only ever be right for the one index it was written
  against. So there is no `Template` type and no `--template`: `--search-fields`
  (or `--search-query-file`), `--field-spec`, `--search-engine`,
  `--mapper-code-file` and `--proxy-requests` supply it, and the defaults are
  Quepid's own (`multi_match` over `*`, `id:_id`, `es`). What a `searchapi`
  endpoint needs to be readable at all — the Qdrant response mapper from the
  articles — ships as `quepid_datasets/mappers/qdrant.js` for
  `--mapper-code-file`, not as a canned per-dataset configuration.
- **`--doc-id-map` and `--query-options-file` are the deliberate escape hatches.**
  Neither ratings' document ids nor per-query vectors survive the trip from a
  dataset to an arbitrary index: Qdrant point ids are assigned when *you* index,
  and a CLIP vector requires a model this project has no business shipping. Both
  flags are dataset-agnostic, and unmapped judgements are dropped with a count
  rather than posted to score nothing.
- **One module per dataset under `quepid_datasets/datasets/`.** `base.py` holds
  what they share (`Dataset`, `DatasetQuery`),
  `wands.py` and `esci.py` import from it, and `__init__.py` re-exports both —
  so imports run one way. Putting the shared definitions in `__init__.py`
  instead makes the package and its dataset modules import each other; that
  happens to work and stops working when the order changes. Adding a dataset is
  `<name>.py` with its `files` to download and a `read(directory)` yielding
  `DatasetQuery`, plus a line in `DATASETS`. Nothing in the commands is
  dataset-aware.
- **`pyarrow` is imported inside `esci.read`, never at module scope.** ESCI ships
  as parquet; `settings.py` imports nothing from this app but Django imports the
  command module to build `--help`, so a top-level import would make the whole
  CLI fail wherever pyarrow is missing. The app image needs a rebuild to have it.
- The app is named `quepid_datasets`, not `datasets`, because that name is taken
  by a distribution this project could plausibly install — see "Naming apps".

## The MCP server

A second, read-only API over the same models and the same bearer tokens, served
at **`/mcp/mcp`** (the doubled segment is required — see `docs/mcp-server-plan.md`
§2). 13 collections, queried with a MongoDB-style aggregation pipeline.

Point a client at it by exporting a Quepid-issued token; `.mcp.json` is checked
in and reads it from the environment, so it never holds a secret:

```bash
export QUEPID_MCP_API_KEY=<token from thor user:add_api_key>
```

Two things about it are counter-intuitive and are the source of most mistakes:

- **`fields` on a toolset is NOT an access control.** django-mcp-server uses it
  only to build the advertised JSON schema; the query itself ends at
  `queryset.values()` with no arguments, so **every column of a published model
  is returned**, and `$match` can filter on unpublished columns too. Verified
  over HTTP: a `searchendpoints` row declares 9 fields and returns 14, including
  `basic_auth_credential`. Publishing a model exposes the whole row — which is
  why `Users` is not published at all, matching the REST API, which has no users
  schema or router either.
- **Unlike the ninja routers, MCP scopes rows.** Every toolset filters to the
  token owner and the teams they belong to (`quepid_mcp/mcp.py:QuepidScoped`);
  Quepid administrators bypass it. An empty result means "not shared with you",
  not "does not exist".

`docs/mcp-server-plan.md` is the design record — §0 lists the blockers found by
auditing the installed `django-mcp-server` source, and §3.2 explains the
`fields` finding. `docs/mcp-server-playbook.md` is the portable, project-agnostic
version of the same guide.
