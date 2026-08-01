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
- **Path ambiguity to watch.** `quepid/` at the repo root is the Rails
  submodule; `quepid_api/quepid/` is this project's Django app holding the
  `inspectdb` models. Elsewhere in this file, bare `quepid/models.py` and
  `quepid/schemas.py` mean the Django app.

## Commands

There is no build step and no test suite (see "Testing" below). Development runs
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

Release: the version in `package.json` is the source of truth; pushing a `v*`
tag triggers `.github/workflows/docker-image.yml`, which builds and pushes the
`app` and `web` Docker targets. `APP_VERSION` env var feeds the version shown in
the OpenAPI schema.

## The Rails-owned schema — the central constraint

`quepid/models.py` is **`inspectdb` output** reflecting Quepid's Rails schema.
Consequences that are easy to get wrong:

- **`models.py` must stay pure `inspectdb` output. This is a hard requirement.**
  It is a generated file and has to remain regenerable: the only acceptable way
  to change it is to re-run `inspectdb` against a migrated Quepid database.
  Never hand-add properties, methods, managers, `__str__`, validation or any
  other behaviour to it — a regeneration would silently drop them. When
  something needs to *behave* like a model (e.g. a `Users` row that has to
  satisfy DRF's `IsAuthenticated`), adapt it at the boundary that needs it and
  leave the model alone; `quepid_mcp/auth.py:QuepidPrincipal` is the worked example.
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
  `Judgements.user_id`, `Snapshots.try_id`, and the `Teams*` junction tables.
  These cannot be traversed with `select_related`, `__` lookups, or joins; fetch
  the target row separately by pk. Real `ForeignKey`s do exist elsewhere
  (`Queries.case`, `Ratings.query`, `QueryDocPairs.book`, `Cases.owner`, …), so
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

`requirements.txt` pulls in `pytest`, `pytest-django`, `pytest-cov` and
`pytest-playwright`, but **no tests, no `conftest.py` and no pytest
configuration exist**. Adding the first test means also adding pytest config
that sets `DJANGO_SETTINGS_MODULE=quepid_api.settings`. Note that unit tests
would need either a live Quepid MySQL or mocking, since the models are
unmanaged and pytest-django cannot create a test database for them.

## The MCP server

A second, read-only API over the same models and the same bearer tokens, served
at **`/mcp/mcp`** (the doubled segment is required — see `docs/mcp-server-plan.md`
§2). 14 collections, queried with a MongoDB-style aggregation pipeline.

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
