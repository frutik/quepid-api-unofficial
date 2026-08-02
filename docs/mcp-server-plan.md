# MCP Server for quepid-api-unofficial — implementation plan

Derived from `docs/mcp-server-playbook.md`, adapted to this repo after auditing
`quepid_api/` and the installed source of `django-mcp-server` 0.5.7.

Goal: a read-only MCP server at `/mcp/mcp`, authenticated with **the same
Quepid API token the django-ninja API already accepts**, exposing the Quepid
MySQL schema as queryable collections.

> **This is a design record, written against Quepid v8.1.0 models. It is not
> maintained as a description of the current server.** The v8.5.0 upgrade
> (2026-08-02) dropped the `selectionstrategies` collection, leaving **13**, and
> removed `scorer_id` / `selection_strategy` from `books` — so the whitelist in
> §3.3, the phase-2 list in §3.4 and the real-FK list in §3.5 are all one
> version behind. `quepid_api/quepid_mcp/mcp.py` is the source of truth for what
> is published; `docs/quepid-compatibility.md` explains what moved and why.
> The findings in §0 and §3.2 are version-independent and still hold.

---

## 0. Blockers found during the audit — fix these first

These are not in the playbook; they are specific to this repo.

### 0.1 `quepid_api/mcp/` shadows the `mcp` PyPI package — HARD BLOCKER

`quepid_api/mcp/__init__.py` is a tracked leftover (507 bytes) that references
an undefined `api` symbol and is imported by nothing. The Django project root
`quepid_api/` is on `sys.path` (it is `manage.py`'s directory and the Docker
`WORKDIR`), so this directory *is* the module `mcp`. Installing the MCP SDK and
doing `from mcp.server import FastMCP` would import this file instead and blow
up at startup.

**Action: `git rm -r quepid_api/mcp/`.** It is dead code.

### 0.2 django-mcp-server hard-depends on DRF

The playbook's §1 table says "Middleware-level auth, not DRF — a 20-line
middleware beats pulling in DRF". That is not achievable here:
`mcp_server/urls.py` does `from rest_framework.permissions import IsAuthenticated`
at module level, and `mcp_server/views.py` subclasses `rest_framework.views.APIView`.
`djangorestframework>=3.15.0` is a declared dependency. DRF is coming in
regardless — so we should use its auth hook rather than fight it (see §3).

### 0.3 Session engine is imported at startup, and `django.contrib.sessions` is not installed

`DjangoMCP.__init__` runs `import_module(settings.SESSION_ENGINE)`
unconditionally at app-ready time. Default is
`django.contrib.sessions.backends.db`, which imports `Session` — a model in an
app that is **commented out** of `INSTALLED_APPS` in `settings.py:29`. Django
raises `RuntimeError: Model class ... isn't in INSTALLED_APPS`.

Compounding it: nothing in the Dockerfile runs `migrate`, so the `django_session`
table does not exist in the default sqlite DB anyway.

**Action:** run the server in stateless mode and use a cookie-backed engine:

```python
INSTALLED_APPS = [..., 'django.contrib.sessions', 'rest_framework', 'mcp_server']
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'
DJANGO_MCP_GLOBAL_SERVER_CONFIG = {..., 'stateless': True}
```

`stateless: True` is safe: `DjangoMCP.session_manager` already hardcodes
`stateless=True` on the underlying `StreamableHTTPSessionManager`; the flag only
controls whether a *Django* session is layered on top. We publish read-only
tools, so there is no per-session state to keep. This also means the playbook's
§9 note about `400 "Session required for stateful server"` does not apply — a
bare POST works.

### 0.4 Toolsets must be pinned to the `quepid` alias

`ModelQueryToolset.get_queryset()` returns `self.model._default_manager.all()` —
no `.using()`, no router hook. It routes to `default`, which is sqlite
(`settings.py:71-75`) and where none of the Quepid tables exist.

**The database configuration stays as it is** — two aliases, `default` sqlite
and `quepid` MySQL — and every query keeps reaching the real data through an
explicit `.using('quepid')`, matching the rest of the codebase
(`api/utils.py:16`, `api/cases.py:52`, …) and the rule recorded in `CLAUDE.md`.

**Action:** a shared toolset base class that pins the alias. Preferred over a DB
router, which would silently change routing for the existing ninja code paths
too:

```python
# quepid_mcp/mcp.py
class QuepidQueryToolset(ModelQueryToolset):
    def get_queryset(self):
        return self.model._default_manager.using('quepid').all()
```

`.using()` propagates through the joins that `$lookup` generates, so one
override at the base covers the whole pipeline. Every scoped subclass (§3.6)
calls `super().get_queryset()` and therefore inherits the alias for free —
subqueries used in those filters must carry `.using('quepid')` as well.

### 0.5 Version compatibility to verify before writing code

`requirements.txt` pins `Django==6.0.6`. django-mcp-server 0.5.7 declares
`django>=4.0`; DRF added Django 6.0 support in the 3.17 line (latest 3.17.1).
Confirm `python -c "import rest_framework, mcp_server"` works on Django 6.0.6
before proceeding. If DRF turns out to be incompatible, the fallback is pinning
Django back to 5.2.x — decide before writing toolsets, not after.

---

## 1. Authentication — reuse the ninja token path exactly

Today's ninja auth (`api/utils.py:7-19`): read `Authorization: Bearer <tok>`,
look up `ApiKeys.token_digest == tok` on the `quepid` alias, return the matching
`Users` row. We want *one* implementation shared by both APIs, not a copy.

### 1.1 New `common/auth.py` (shared) and `quepid_mcp/auth.py` (DRF)

The token lookup lives in `common/auth.py` — not in the `quepid` app, which is
kept to the inspectdb reflection, and not in either API surface, since both call
it. It is free of ninja, DRF and MCP imports. The DRF plumbing
(`QuepidPrincipal`, `QuepidTokenAuthentication`) lives in `quepid_mcp/auth.py`
and imports `user_from_token` from it.

```python
def user_from_token(token):
    """Resolve a Quepid API token to its Users row, or None.

    Single source of truth for both the ninja API (api.utils.AuthBearer)
    and the MCP endpoint (QuepidTokenAuthentication).
    """
    try:
        api_key = ApiKeys.objects.using('quepid').get(token_digest=token)
        return Users.objects.using('quepid').get(pk=api_key.user_id)
    except (ApiKeys.DoesNotExist, Users.DoesNotExist):
        return None


class QuepidTokenAuthentication(BaseAuthentication):
    keyword = 'Bearer'

    def authenticate(self, request):
        header = request.headers.get('Authorization', '')
        parts = header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            return None
        user = user_from_token(parts[1])
        if user is None:
            raise AuthenticationFailed('Invalid token')
        return (user, parts[1])

    def authenticate_header(self, request):
        return self.keyword          # produces WWW-Authenticate: Bearer on 401
```

Then rewrite `api/utils.AuthBearer.authenticate` to `return user_from_token(token)`.
Behaviour is unchanged; the bare `except:` at `api/utils.py:18` gets narrowed as
a side effect.

### 1.2 Wire it into the MCP endpoint

```python
DJANGO_MCP_AUTHENTICATION_CLASSES = ['quepid_mcp.auth.QuepidTokenAuthentication']
```

`mcp_server/urls.py` reads this setting and, when it is non-empty, applies
`permission_classes=[IsAuthenticated]` automatically. Unauthenticated requests
get a DRF `401` with `WWW-Authenticate: Bearer`.

### 1.3 `QuepidPrincipal` — the adapter, NOT a model change

`IsAuthenticated` evaluates `bool(request.user and request.user.is_authenticated)`.
`quepid.models.Users` is an `inspectdb` model with no such attribute, so every
request would 403.

`models.py` must stay pure `inspectdb` output (see `CLAUDE.md`), so the flag
cannot live on the model — a regeneration would silently drop it. Instead
`quepid_mcp/auth.py` wraps the row:

```python
class QuepidPrincipal:
    is_authenticated = True
    is_anonymous = False

    def __init__(self, quepid_user):
        self.quepid_user = quepid_user

    def __getattr__(self, name):
        return getattr(self.quepid_user, name)
```

`QuepidTokenAuthentication` returns `QuepidPrincipal(user)`, so
`self.request.user` in a toolset exposes `.id` and `.administrator` by
delegation while satisfying DRF. The ninja API is untouched — it keeps getting
the bare `Users` row, which matters because it assigns it straight to an owner
FK (`owner=request.auth`).

### 1.4 Why the DRF hook and not the playbook's middleware (§5.2)

The playbook's `McpApiKeyMiddleware` sets `request.user` on the *Django*
request. But `_call_starlette_handler` stashes the **DRF** `Request` in a
contextvar (`djangomcp.py:81`), and that is what arrives as `self.request`
inside `ModelQueryToolset.get_queryset()` (`djangomcp.py:148`).

With `authentication_classes=[]`, DRF's `Request.user` resolves to
`AnonymousUser` — and not merely by shadowing: DRF's `user` **setter writes
through to `self._request.user`**, so `_not_authenticated()` overwrites what the
middleware put on the Django request. Verified empirically: given a middleware
that sets `django_request.user = <Users>`, both `drf_request.user` and
`drf_request._request.user` come back `AnonymousUser`. There is no fallback
attribute to reach for.

That makes the middleware route unusable for the row scoping in §1.5, since
`AnonymousUser` has no `.id`. The DRF authentication class puts the real `Users`
instance on `self.request.user` — the exact analogue of ninja's `request.auth` —
and it keys off the route rather than a hardcoded URL-prefix string match.

If `models.py` must stay pure `inspectdb` output (§1.3 adds two properties to
`Users`), the one working alternative is a middleware that stashes the user
under a name DRF does not manage — `request._quepid_user` — read back as
`self.request._request._quepid_user`. It costs the closed-by-default behaviour
and pokes at a private attribute. Rejected here, but recorded because it is the
only middleware variant that actually works.

### 1.5 Row-level scoping — deliberate non-goal for v1

The existing ninja endpoints do no per-user filtering at all
(`api/cases.py:51` is literally `# @todo check rights?`; any valid token sees
every case). The MCP server will **mirror that**: any valid token can query
every published collection. This is the "same way as ninja" reading of the
requirement. If you want MCP to be stricter than the REST API, say so — the
hook is `get_queryset()` on the base toolset (playbook §8.5), and
`self.request.user` is already the right object. Flagging it rather than
deciding it silently.

---

## 2. Settings and URL changes

`quepid_api/settings.py`:

```python
INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',      # uncommented — see §0.3
    'django.contrib.staticfiles',
    'rest_framework',
    'mcp_server',
    'quepid',
]

SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'

# DATABASES is unchanged -- toolsets pin .using('quepid') themselves (§0.4)

REST_FRAMEWORK = {
    # keep BrowsableAPIRenderer out of content negotiation entirely
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
}

DJANGO_MCP_AUTHENTICATION_CLASSES = ['quepid_mcp.auth.QuepidTokenAuthentication']
DJANGO_MCP_GLOBAL_SERVER_CONFIG = {
    'name': 'quepid',
    'stateless': True,
    'instructions': '...',           # §4
}
```

No `MIDDLEWARE` change — we are not using the playbook's middleware.

`quepid_api/urls.py`:

```python
urlpatterns = [
    path("api/", api.urls),
    path("mcp/", include('mcp_server.urls')),   # endpoint is /mcp/mcp
]
```

The library appends its own `mcp` segment (`DJANGO_MCP_ENDPOINT`, default
`"mcp"`), so the client URL is `/mcp/mcp` with **no trailing slash**. Do not try
to collapse this to `/mcp/` by setting `DJANGO_MCP_ENDPOINT = ""` —
`CommonMiddleware`'s `APPEND_SLASH` would 301 the POST and break the transport.

There is no `admin/` mount here, so the playbook's §4 ordering warning does not
apply. `nginx.conf` proxies `/` wholesale, so no nginx change is needed either.

`requirements.txt` additions:

```
mcp<2.0.0
django-mcp-server==0.5.7
djangorestframework>=3.17.1
```

---

## 3. Collections

One `quepid_mcp/mcp.py`, all toolsets subclassing `QuepidQueryToolset` (§0.4), which
pins the `quepid` alias and applies the team scoping described in §3.6.

Collection names are the bare lowercase model names, so they come out plural
(`Cases` → `cases`, `QueryDocPairs` → `querydocpairs`). All models live in the
single `quepid` app, so playbook §8.1 (name collisions) and §8.3 (proxy FKs) do
not apply.

### 3.1 Never publish

`ApiKeys` (it is the credential store), plus all operational noise:
`Ahoy*`, `Blazer*`, `SolidQueue*`, `SolidCable*`, `ActiveStorage*`,
`SchemaMigrations`, `ArInternalMetadata`, `WebRequests`, `Announcements`,
`AnnouncementViewed`, `CuratorVariables`.

### 3.2 Secrets — `fields` does not protect them

**Superseded by a finding during implementation.** This section used to list
"fields that must be excluded for secrecy" as a `fields` whitelist. That does
not work: `fields` only shapes the advertised schema (playbook §8.4 records the
detail). Every column of a published model is readable, and filterable, no
matter what `fields` says.

What was actually done, on the principle of matching the ninja REST API:

- **`Users` is not published at all.** It holds password hashes, reset tokens
  and invitation tokens, and the REST API does not expose it either — there is
  no `Users` schema in `quepid/schemas.py` and no users router in `api/`. Not
  publishing it removes the exposure rather than masking it. The cost is that
  `owner_id` / `user_id` columns elsewhere are terminal ids: `Cases.owner` is
  auto-excluded once its target model is unpublished.
- **`SearchEndpoints` is published as-is.** Its `basic_auth_credential`,
  `custom_headers` and `mapper_code` columns are already returned to the same
  token by `GET /api/search_endpoints/`, because `SearchEndpoint` is declared
  `fields = "__all__"`. MCP therefore adds no new exposure. Its
  `extra_instructions` tell the client not to select or report those columns —
  guidance, not enforcement.
- **`CaseScores` is not published.** Its `queries` column is a `BinaryField`;
  with no way to restrict the SELECT list it would hand raw bytes to the JSON
  renderer.

`fields` is still set on every toolset, but purely to keep the advertised schema
small and readable (§8.4's real purpose).

### 3.3 Phase 1 — 8 collections, then verify

Playbook §8.4 is the highest-risk item here: every published model's JSON schema
is concatenated into **one** tool description, and blowing the client's
truncation limit silently hides the entire collection list. With ~16 candidate
models, ship in two passes and check the list renders in between.

| Collection | Model | Whitelist |
|---|---|---|
| `cases` | `Cases` | id, case_name, last_try_number, owner, archived, scorer_id, book_id, public, nightly, created_at, updated_at |
| `queries` | `Queries` | id, query_text, information_need, notes, case, created_at, updated_at |
| `ratings` | `Ratings` | id, doc_id, rating, query, user_id, created_at, updated_at |
| `books` | `Books` | id, name, scorer_id, owner_id, selection_strategy, support_implicit_judgements, show_rank, created_at, updated_at |
| `querydocpairs` | `QueryDocPairs` | id, query_text, doc_id, position, information_need, notes, document_fields, book, created_at, updated_at |
| `judgements` | `Judgements` | id, rating, unrateable, judge_later, explanation, query_doc_pair, user_id, created_at, updated_at |
| `users` | `Users` | id, name, email, company, administrator, locked, num_logins, default_scorer, created_at, updated_at |
| `teams` | `Teams` | id, name, created_at, updated_at |

`document_fields` is the one judgement call: it is the actual indexed document
content (a JSON text blob) and is what makes `querydocpairs` useful, but rows
are fat. Include it, and say in `extra_instructions` to `$project` it away
unless the question needs it.

### 3.4 Phase 2 — add after phase 1 verifies clean

`scorers`, `searchendpoints`, `tries`, `snapshots`, `snapshotqueries`,
`casescores`, `selectionstrategies`, `teamsmembers`, `teamscases`.

`TeamsBooks` and `TeamsSearchEndpoints` are junction tables declared with plain
`BigIntegerField`, not FKs — publishing them buys nothing a `$lookup` can use.
Skip unless asked.

### 3.5 The instruction trap specific to this schema

Half the "foreign keys" in `quepid/models.py` are **plain `IntegerField`s**, a
consequence of the `inspectdb` generation. Real FKs (traversable by `$lookup`):
`Cases.owner`, `Queries.case`, `Ratings.query`, `Judgements.query_doc_pair`,
`QueryDocPairs.book`, `Books.selection_strategy`, `Users.default_scorer`,
`Tries.case`, `Tries.search_endpoint`, `Snapshots.case`, `SnapshotQueries.query`,
`SnapshotQueries.snapshot`, `SearchEndpoints.owner`, `CaseScores.case`,
`CaseScores.user`, `TeamsCases.*`, `TeamsMembers.*`.

Raw integers that **look** like references and are not: `Cases.scorer_id`,
`Cases.book_id`, `Books.scorer_id`, `Books.owner_id`, `Ratings.user_id`,
`Judgements.user_id`, `Scorers.owner_id`, `Snapshots.try_id`,
`Snapshots.scorer_id`, `CaseScores.try_id`, `CaseScores.scorer_id`,
`BookMetadata.user_id`.

Every affected toolset's `extra_instructions` must say, in these words: *"`X_id`
is a raw id, NOT a reference — `$lookup` cannot traverse it. Query the other
collection separately with `$match: {id: ...}`."* Clients will otherwise emit
`$lookup` stages that fail, and they will do it every session.

Also apply playbook §8.8 everywhere: `localField` must be the Django field name
(`case`, `owner`, `query`), not the `_id`-suffixed form that shows up in results
(`case_id`, `owner_id`).

Boolean semantics worth spelling out: `archived`, `public`, `nightly`,
`administrator`, `locked`, `unrateable`, `judge_later`, `all_rated` are MySQL
tinyints surfaced as `IntegerField` — `1`/`0`/`null`, and **`null` is not
`false`**. `Ratings.rating` is a float on a per-scorer scale, not a fixed range.

No computed fields (playbook §8.6) are needed for v1, and no cross-database
links (§8.7) exist — everything is in the one `quepid` alias.

---

## 4. Global instructions

Per playbook §7, a map of the domain, not the territory. Draft:

> Quepid exposes read-only query access to a Quepid search-relevance testing
> database. Collections: "cases" (relevance test cases), "queries" (search
> queries inside a case; queries.case → cases), "ratings" (human relevance
> judgements per query/document; ratings.query → queries), "books" (shared
> judgement collections), "querydocpairs" (query/document pairs inside a book;
> .book → books), "judgements" (book-level ratings; .query_doc_pair →
> querydocpairs), "users" and "teams". A case is a live search-tuning workspace;
> a book is the reusable judgement corpus behind it. Resolve references in one
> query with $lookup instead of returning raw ids, and use the Django field name
> as localField ("case", "query", "owner"), not the "_id" form seen in results.
> Many *_id columns (cases.scorer_id, cases.book_id, ratings.user_id,
> judgements.user_id, books.owner_id) are raw integers with no FK — $lookup
> cannot traverse them; query the target collection separately by id. "Latest"
> means highest id, or sort by created_at/updated_at descending. Boolean-looking
> fields (archived, public, nightly, all_rated) are tinyints where null is
> distinct from 0.

Per-collection detail goes in `extra_instructions`, written against playbook
§8.9.

---

## 5. Build order

1. `git rm -r quepid_api/mcp/` (§0.1).
2. Add the three requirements; verify `import rest_framework, mcp_server`
   under Django 6.0.6 (§0.5). **Stop here if DRF is incompatible.**
3. `common/auth.py` (shared lookup) + `quepid_mcp/auth.py` (DRF adapter) +
   refactor `api/utils.AuthBearer` (§1). Verify the ninja API still
   authenticates — this touches shipped code.
4. Settings + urls (§2). `DATABASES` is untouched. Verify Django starts,
   `/api/docs` still loads, and an existing ninja endpoint still returns rows —
   the `AuthBearer` refactor (§1.1) is the one edit that touches shipped
   behaviour.
5. `quepid_mcp/mcp.py`: base class (§0.4), scoping helpers (§3.6), then the 8
   phase-1 toolsets with `fields` whitelists only, no `extra_instructions` yet.
6. Run the playbook §9 verification ladder. Confirm all 8 collections are
   visible in `/mcp`.
7. Write `extra_instructions` (§3.5) and the global instructions (§4).
8. Add phase-2 collections (§3.4). **Re-verify the full list is still visible**
   after each batch — this is the §8.4 failure mode and it is silent.
9. Client config per playbook §12 — `.mcp.json` with
   `Authorization: Bearer ${QUEPID_MCP_API_KEY}`, never a literal token.

## 6. Verification, adapted

Playbook §9, with two changes for this repo:

```bash
# 1. toolsets import, models resolve
./manage.py shell -c "import quepid.mcp"

# 2. unauthenticated -> 401 + WWW-Authenticate: Bearer
curl -i -X POST http://localhost:8081/mcp/mcp

# 3. authenticated initialize -> 200 (NOT 400 "Session required":
#    we run stateless, so no mcp-session-id handshake)
curl -i -X POST http://localhost:8081/mcp/mcp \
  -H "Authorization: Bearer $QUEPID_MCP_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0.1"}}}'

# 4. same token must still work against the ninja API (regression check on §1)
curl -s -H "Authorization: Bearer $QUEPID_MCP_API_KEY" \
  http://localhost:8081/api/teams/ | head

# 5. from a client
claude mcp list
```

Then ask the client two questions: one needing a `$lookup` (*"which case does
query N belong to, by name?"*) and one hitting the raw-id trap (*"what book is
case N using?"* — must **not** be answered with a `$lookup` on `book_id`). If
either misbehaves, the fix is in the instruction strings, not the code.

## 7. Open question for the user

Row-level scoping (§1.5). Default assumed: **none** — mirrors the current ninja
API, where any valid token reads everything. Say the word if MCP should instead
be scoped to the token's user and their teams.
