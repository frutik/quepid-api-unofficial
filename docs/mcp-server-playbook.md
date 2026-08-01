# Django MCP Server — Portable Build Playbook

> **Audience: an AI coding agent (or engineer) asked to add a read-only MCP query
> server to a Django project.** This document is self-contained and
> project-agnostic. Copy it into any Django repo (`docs/mcp-server-playbook.md`)
> and instruct the agent: *"Build the MCP server described in
> `docs/mcp-server-playbook.md` for this project."*
>
> Every code block is a template. Replace `<ANGLE_BRACKET>` placeholders.
> The "Reference implementation" column in §11 points at the TAXI project this
> playbook was extracted from — ignore it if you copied this file elsewhere.

---

## 1. What this builds

A Model Context Protocol (MCP) server, served by your existing Django app over
streamable HTTP, that exposes **read-only, aggregation-capable query access to
selected Django models**. MCP clients (Claude Code, Claude Desktop, any MCP
client) see the models as *collections* and query them with a MongoDB-style
aggregation pipeline (`$match`, `$lookup`, `$sort`, `$project`, `$group`,
`$limit`).

Architecture:

```
MCP client (Claude Code)
   │  HTTP + Bearer token
   ▼
<PROJECT>/urls.py            → path("<MOUNT>/", include("mcp_server.urls"))
   │
   ├─ <AUTH_APP>/middleware.py  → McpApiKeyMiddleware (bearer → ApiKey → request.user)
   │
   └─ django-mcp-server
        │  autodiscovers <app>/mcp.py in every INSTALLED_APP
        ▼
      ModelQueryToolset subclasses  → one MCP "collection" per model
        │
        ▼
      Django ORM (querysets, annotations, DB routers)
```

Design decisions baked in (keep them unless you have a reason not to):

| Decision | Why |
|---|---|
| **Read-only** | The toolset base class only queries. No write tools are published. |
| **Static bearer token, not OAuth** | MCP clients send configured headers on every request; a shared secret is enough for an internal tool. |
| **Reuse the project's existing API-key model** | One place to issue/revoke credentials; no new auth surface. |
| **Middleware-level auth, not DRF** | The MCP endpoint is a single mounted URL tree; a 20-line middleware beats pulling in DRF. |
| **One `mcp.py` per Django app** | Toolsets live next to the models they publish; autodiscovery does the wiring. |
| **Explicit `fields` whitelist on every toolset** | Non-negotiable. See §8.4. |

---

## 2. Prerequisites

```
# requirements.txt
mcp<2.0.0
django-mcp-server
```

Pin whatever `django-mcp-server` version you install and **verify the API
surface against the installed source** before writing toolsets — this playbook
was validated against **0.5.7**. Check:

```bash
python -c "import mcp_server, os, importlib.metadata as m; \
print(m.version('django-mcp-server')); print(os.path.dirname(mcp_server.__file__))"
```

Then read `<pkg>/djangomcp.py` and `<pkg>/apps.py` in that directory. If class
names or hook names differ from this document, **the installed source wins** —
update this file with what you find (§10).

---

## 3. Step 1 — Settings

```python
# <PROJECT>/settings.py

INSTALLED_APPS = [
    ...,
    'mcp_server',
]

DJANGO_MCP_GLOBAL_SERVER_CONFIG = {
    'name': '<SERVER_NAME>',          # the name clients show, e.g. "taxi"
    'instructions': (
        # See §7 — this is the single most important prompt in the system.
    ),
}

MIDDLEWARE = [
    ...,
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    '<AUTH_APP>.middleware.McpApiKeyMiddleware',   # must come AFTER auth middleware
    ...,
]
```

`McpApiKeyMiddleware` overwrites `request.user`, so it must run *after*
`AuthenticationMiddleware` has set the session-based one.

**Multi-mode projects:** if your project runs the same codebase as web / worker /
etc. (e.g. a `MODE` env var), register `mcp_server` and the MCP URL only in the
web/admin mode. A Celery worker has no business serving MCP.

---

## 4. Step 2 — URLs

```python
# <PROJECT>/urls.py
path("<MOUNT>/", include('mcp_server.urls')),
```

The library adds its own `mcp` sub-path under your mount, so the endpoint
clients actually connect to is `<MOUNT>/mcp`:

```
https://<HOST>/<MOUNT>/mcp        e.g. https://host/admin/mcp/mcp
```

That sub-path is the `DJANGO_MCP_ENDPOINT` setting, default `"mcp"`.

⚠️ **Do not set `DJANGO_MCP_ENDPOINT = ""` to collapse the doubled segment.**
It looks tidier (`/<MOUNT>/` instead of `/<MOUNT>/mcp`) and it breaks the
transport: the route then only matches with a trailing slash, and Django's
`CommonMiddleware` `APPEND_SLASH` answers the client's `POST /<MOUNT>` with a
301. MCP clients do not replay a POST body across a redirect, so the session
fails to initialize with no useful error. Live with the doubled segment, or
change the mount rather than the endpoint.

⚠️ **Ordering:** if you mount under `admin/`, the route must be registered
*before* `path('admin/', admin.site.urls)` — the Django admin has a final
catch-all pattern that shadows anything registered after it.

---

## 5. Step 3 — Authentication

### 5.1 The API-key model

Reuse the project's existing key model if there is one. If not, this is the
minimum contract the middleware needs — a lookup classmethod that enforces
enabled/expiry and returns the key (or `None`):

```python
# <AUTH_APP>/models.py
import uuid
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class ApiKey(models.Model):
    name       = models.CharField(max_length=255)
    enabled    = models.BooleanField(default=True)
    key        = models.UUIDField(default=uuid.uuid4)
    user       = models.ForeignKey(User, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    added_at   = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def check_token(cls, bearer):
        return cls.objects.filter(
            key=bearer, enabled=True,
        ).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        ).first()

    def __str__(self):
        return self.name
```

Register it in the Django admin so keys can be issued and revoked without a
deploy. The optional `user` FK is what makes per-user row filtering possible
(§8.5).

### 5.2 The middleware

```python
# <AUTH_APP>/middleware.py
import logging

from django.http import JsonResponse

from <AUTH_APP>.models import ApiKey

logger = logging.getLogger(__name__)

MCP_PATH = '/<MOUNT>/'          # e.g. '/admin/mcp/' — leading and trailing slash


class McpApiKeyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(MCP_PATH):
            return self.get_response(request)

        try:
            bearer = request.headers.get('Authorization').split()[1]
            token = ApiKey.check_token(bearer)
        except Exception as e:
            logger.error(f'Invalid MCP authorization header: {e}')
            token = None

        if not token:
            return JsonResponse(
                {'error': 'unauthorized'},
                status=401,
                headers={'WWW-Authenticate': 'Bearer'},
            )

        if token.user:
            request.user = token.user

        return self.get_response(request)
```

The broad `except Exception` is deliberate: a missing header
(`None.split()`), a malformed one (`IndexError`), and a non-UUID value
(`ValidationError` from the UUID field lookup) all mean the same thing — 401.

---

## 6. Step 4 — Publish a collection

Create `mcp.py` in the Django app that owns the model. The library autodiscovers
`<app>/mcp.py` for every entry in `INSTALLED_APPS`; there is nothing else to
register.

```python
# <APP>/mcp.py
from mcp_server import ModelQueryToolset
from .models import <MODEL>


class <MODEL>QueryTool(ModelQueryToolset):
    model = <MODEL>
    fields = ['id', '<field>', '<field>', ...]      # REQUIRED — see §8.4
    extra_instructions = (
        '<What this collection is, in one or two sentences.> '
        '<Which fields are references and to which collection. > '
        '<What "latest" means. > '
        '<Any field whose meaning is not obvious from its name.>'
    )
```

The collection name clients see is the **bare lowercase model name**
(`Shop` → `shop`, `FeedImport` → `feedimport`). It is not namespaced by app —
which is the source of the clash problem in §8.1.

That is the entire happy path. Everything below is for the cases that are not
the happy path.

---

## 7. Step 5 — Write the server instructions

`DJANGO_MCP_GLOBAL_SERVER_CONFIG['instructions']` is delivered to the client
once, up front, and is the client's *only* map of the data model. Budget real
effort here — a wrong or vague instruction string produces confidently wrong
queries.

It must cover:

1. **One line of scope.** "`<SERVER_NAME>` exposes read-only query access to `<DOMAIN>`."
2. **The collection list**, each with a ≤10-word gloss, grouped by subsystem.
3. **How collections relate.** Which field on which collection points where.
4. **A standing instruction to resolve references with `$lookup`** rather than
   returning raw ids — otherwise clients emit id numbers the user can't read.
5. **What "latest"/"newest" means** in this schema (highest id? a timestamp?).
   Clients guess otherwise, and guess differently each time.
6. **Computed fields and the shortcuts they enable** (§8.6) — these do not
   appear in any generated schema, so if they are not written here they do not
   exist as far as the client is concerned.

Worked example (adapt the shape, not the content):

```python
DJANGO_MCP_GLOBAL_SERVER_CONFIG = {
    'name': 'taxi',
    'instructions': (
        'TAXI exposes read-only query access to the MIAB e-commerce platform. '
        'Collections: "shop" (webshops), "market" (countries, e.g. nl/be/ae), '
        '"feed" (product feed sources; shop.source_feed points here) and '
        '"feedimport" (Pepelaco feed import runs), "pepelacoshop" (shops as '
        'known to the Pepelaco import platform), "pepelacosource" (the import '
        'sources those shops belong to) and "productimportershopimport" '
        '(taxi-side product importer runs per feed). Every shop belongs to a '
        'market via its "market" reference; resolve references in one query '
        'with a $lookup instead of returning raw ids. "Latest" means highest '
        'id (or sort by "added"/"started_at" descending). The pepelaco '
        'collections carry a computed "market" field holding the market name '
        '(e.g. "webshop_be") — match on it directly to scope by market instead '
        'of joining; feedimport also carries a computed "error_count" for '
        'finding runs with feed errors.'
    ),
}
```

Per-collection detail goes in that toolset's `extra_instructions`, not here.
Keep the global string to the map; keep the territory in the toolsets.

---

## 8. Patterns and pitfalls

These are hard-won. Read all of them before publishing your second collection.

### 8.1 Colliding model names silently clobber each other

Collections are keyed by lowercase `model_name` with **no app namespace**. Two
published models named `FeedImport` in different apps → one silently wins.

**Fix: publish a proxy model with a distinct name.**

```python
# <APP>/models.py
class <DISTINCT_NAME>(<ORIGINAL_MODEL>):
    """Proxy so the MCP query tool can publish <ORIGINAL_MODEL> under a
    collection name that does not clash with <OTHER_APP>.<ORIGINAL_MODEL>."""

    class Meta:
        proxy = True
```

Then point the toolset at the proxy. Proxy models need a **state-only
migration** (`makemigrations` generates it; it touches no SQL) — do not skip it,
or `migrate --check` will report drift forever.

### 8.2 Proxies + database routers

If the model lives in a secondary database selected by a router, check what the
router matches on. A common pattern is `managed is False`:

```python
class <NAME>Router:
    def is_<db>(self, model):
        return model._meta.app_label == "<APP>" and model._meta.managed is False

    def db_for_read(self, model, **hints):
        return "<DB_ALIAS>" if self.is_<db>(model) else None

    def db_for_write(self, model, **hints):
        return "<DB_ALIAS>" if self.is_<db>(model) else None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == "default"
```

**Django proxies default to `managed = True`, even when the concrete model is
`managed = False`.** A proxy of an unmanaged model therefore stops matching the
router and reads silently hit the wrong database. Always set it explicitly:

```python
class Meta:
    proxy = True
    # <ROUTER> matches on managed=False; without it, reads would go to
    # the default database
    managed = False
```

### 8.3 Foreign keys to a concrete model whose *proxy* is published

The library auto-excludes FK fields whose target model isn't published. That
check compares `related_model` **by exact class**, so an FK declared against the
concrete `Source` is dropped even when `PepelacoSource` (its proxy) *is*
published. Symptom: a field you listed in `fields` just isn't in the schema.

```python
    @classmethod
    def get_excluded_fields(cls):
        excluded = super().get_excluded_fields()
        # the FK targets the concrete <CONCRETE> model, so the published-models
        # check misses the <PROXY> proxy and would drop the field
        excluded.discard('<fk_field>')
        return excluded
```

You need **both** the `fields` whitelist entry *and* this override.

### 8.4 Always set `fields` — this is not optional

The full schema of *every* published model is embedded in **one** tool
description. A single wide model (70 fields, JSON blobs) blows past client
description-truncation limits and **hides the entire collection list**, taking
every other collection down with it. The failure mode is invisible: the server
connects fine, the client just can't see anything.

Whitelist the 8–15 fields that answer real questions. Leave out caches, blobs,
internal flags, and anything you'd never filter or display.

⚠️ **`fields` IS NOT AN ACCESS CONTROL.** It is used in exactly two places —
generating the advertised JSON schema, and picking text-search fields — and it
never touches the queryset. The pipeline ends at `queryset.values()` with *no
arguments*, which selects every column on the model, and `$match` field names
are passed to `filter()` without validation. So:

- every column of a published model is readable regardless of `fields`;
- `.values(*safe)`, `.defer(...)` and `.only(...)` in `get_queryset()` do **not**
  help — the library's terminal `.values()` resets all of them;
- a client can also filter on unpublished columns, which leaks them a bit at a
  time even without selecting them.

**Publishing a model exposes the whole row.** If a table holds password hashes,
tokens or API credentials, do not publish it. Where a subset genuinely must be
exposed, declare a separate unmanaged model over the same `db_table` listing
only the safe columns, and publish that — `.values()` can then only see the
columns you declared, and `$match` on anything else raises `FieldError`.

### 8.5 Per-user filtering

`get_queryset()` is a normal Django hook and `request.user` is set by the
middleware when the API key has a linked user. Scope rows there:

```python
    def get_queryset(self):
        qs = super().get_queryset()
        user = getattr(self.request, 'user', None)     # verify the attribute
                                                       # name in your version
        if user and not user.is_superuser:
            qs = qs.filter(<owner_field>=user)
        return qs
```

### 8.6 Computed fields (annotations)

Annotations added in `get_queryset()` **flow through the whole pipeline**:
`.values()` with no args includes them, and `$match` / `$sort` / `$project` /
`$group` all resolve annotation names. They are the escape hatch for anything
the ORM can express but the client can't.

Two hard constraints:

- **They never appear in the generated schema.** Document every one in
  `extra_instructions` (and the important ones in the global instructions), or
  no client will ever use them.
- **They are not reachable through `$lookup` traversal** from another collection
  — `$lookup` follows FKs only. A computed field needed on two collections must
  be annotated **on each collection separately**.

Also state plainly in `extra_instructions` that a computed field is *not* a
reference — clients will otherwise try to use it as a `$lookup` `localField`.

**Example — a raw-SQL correlated subquery:**

```python
# Table-qualify columns in RawSQL. An unqualified "errors" becomes ambiguous
# the moment the pipeline self-joins the table (e.g. a $lookup on "previous").
ERROR_COUNT_SQL = \
    '(SELECT count(*) FROM jsonb_object_keys("<table>"."errors"))'

    def get_queryset(self):
        return super().get_queryset().annotate(
            error_count=RawSQL(ERROR_COUNT_SQL, [], output_field=IntegerField()),
        )
```

### 8.7 Cross-database relationships

A `$lookup` is a SQL join and cannot cross databases. When the link between two
collections spans databases (or isn't a real FK at all — e.g. a string column
holding another table's UUID), resolve it **in Python** and inline it as a
`Case`/`When` annotation.

```python
def <name>_case(source_field):
    """Case expression resolving <A> to <B>.

    <A> rows (<db A>) only carry <B>'s public id in <col>; <B> lives in
    <db B>, so the bridge cannot be a SQL join — it is resolved here and
    inlined as literals.
    """
    mapping = {
        str(row.<public_id>): row.<label>
        for row in <ModelB>.objects.select_related('<rel>')
    }
    whens = [
        When(**{source_field: pk}, then=Value(mapping[key]))
        for pk, key in <ModelA>.objects.values_list('id', '<col>')
        if key in mapping
    ]
    if not whens:
        return Value(None, output_field=CharField())
    return Case(*whens, default=Value(None), output_field=CharField())
```

Cost and caveats — weigh these before reaching for it:

- Two extra queries per MCP call, and the `CASE` is inlined as literals, so the
  SQL grows linearly with the mapping. Fine for hundreds of rows; cache or
  denormalize at tens of thousands.
- Accepts a lookup path, so the same helper serves both the owning collection
  (`'id'`) and its children (`'shop__source_id'`).

### 8.8 `$lookup` localField naming

`localField` must be the **Django field name** (`market`), not the `_id`-suffixed
attname (`market_id`) that clients see in results. Clients get this wrong by
default — say it explicitly in `extra_instructions`:

```
'localField must be the field name ("market", "source_feed"), not the
 "_id"-suffixed form that appears in results.'
```

### 8.9 Writing good `extra_instructions`

The generated schema gives clients field names and types. `extra_instructions`
must supply everything else. Include:

- **What the collection actually is** — and what it is *not*, when there's a
  near neighbour ("this is the Pepelaco import log, NOT the taxi-side one").
- **Every reference**, by target collection name, with a copy-pasteable
  `$lookup` snippet for the non-obvious ones.
- **Recency semantics** — "latest = highest id", "sort by `started_at` desc".
- **Enum decodings** — `type is 1=MP, 32765=TT, 32767=TAXI`.
- **Null/empty semantics** — `success is null while running`; `errors` `{}` =
  clean vs `null` = no report. Clients cannot infer these and will get them
  backwards.
- **Traps.** If a schema ref reads `Shop` but points at `pepelacoshop`, say so
  in capitals. If two boolean flags look interchangeable, explain the
  difference.
- **Computed fields** — name, meaning, "filterable and sortable but NOT a
  reference".

Write in plain prose addressed to the client, and prefer one concrete example
query over three sentences of explanation.

---

## 9. Verification

Run these in order; each one isolates a different layer.

```bash
# 1. Toolsets import and models resolve (catches typos in `fields`)
python manage.py shell -c "import <APP>.mcp"

# 2. Unauthenticated request is rejected
curl -i https://<HOST>/<MOUNT>/mcp
# expect: 401 + WWW-Authenticate: Bearer

# 3. Authenticated MCP initialize
# expect: 200, an initialize result, and an mcp-session-id response header.
# (A plain GET/POST without a session returns 400 "Session required for
#  stateful server" — the server is stateful; every session starts with
#  an initialize request.)
curl -i -X POST https://<HOST>/<MOUNT>/mcp \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0.1"}}}'

# 4. From a client
claude mcp list          # <SERVER_NAME> should show "connected"
```

Then, inside a Claude Code session, run `/mcp` and confirm the server lists its
tools. **Critically: check that the collection list is visible and complete** —
if a collection is missing, suspect §8.4 (description truncation) or §8.1 (name
clash) before anything else.

Finally, ask the client a question that requires a `$lookup` across two
collections and one that uses a computed field. If it produces raw ids or
ignores the computed field, the fix is in the instruction strings (§7, §8.9),
not in the code.

---

## 10. Adding a collection later — checklist

1. Does the bare lowercase model name collide with an already-published one?
   → proxy model with a distinct name (§8.1) + state-only migration.
2. Does the model live in a secondary database? → check the router still matches
   the proxy (§8.2).
3. Write the toolset with an explicit `fields` whitelist (§8.4).
4. Any FK in `fields` targeting a concrete model whose proxy is published?
   → `get_excluded_fields().discard(...)` (§8.3).
5. Need a value the ORM can compute but the pipeline can't reach? → annotate in
   `get_queryset()` and document it (§8.6).
6. Cross-database link? → Python-resolved `Case`/`When`, never a `$lookup` (§8.7).
7. Write `extra_instructions` against the §8.9 list.
8. Add the collection to `DJANGO_MCP_GLOBAL_SERVER_CONFIG['instructions']` —
   name, one-line gloss, and how it links to the others (§7).
9. Run §9. Confirm the **full** collection list is still visible.
10. **Update this document** if you hit something it didn't warn you about.

---

## 11. Reference implementation (TAXI)

Delete this section if you copied the playbook into another project.

| Concern | File |
|---|---|
| Settings, instructions, middleware registration | `taxydermist/taxydermist/settings.py` |
| URL mount | `taxydermist/taxydermist/urls.py` |
| Bearer auth middleware | `taxydermist/app/middleware.py` |
| API key model | `taxydermist/app/models.py` (`ApiKey`) |
| Simplest toolset (no options) | `taxydermist/taxonomies/mcp.py` (`market`) |
| Whitelist + `$lookup` instructions | `taxydermist/shops/mcp.py` |
| Proxies, computed fields, cross-DB, `RawSQL` | `taxydermist/pepelaco_connect/mcp.py` |
| Proxy models | `taxydermist/shops/models.py` (`ProductImporterShopImport`), `taxydermist/pepelaco_connect/models.py` (`PepelacoShop`, `PepelacoSource`) |
| DB router | `taxydermist/pepelaco_connect/dbrouters.py` |
| Client setup, key management, smoke tests | `docs/mcp-server-auth.md` |

Published collections: `shop`, `market`, `feed`, `feedimport`, `pepelacoshop`,
`pepelacosource`, `productimportershopimport`.

---

## 12. Client configuration

`claude mcp add` writes the config; `--scope` picks which file:

| Scope | Written to | Use for |
|---|---|---|
| `local` (default) | project-specific user config | trying it out |
| `user` | `~/.claude.json` | your personal setup, all projects |
| `project` | `.mcp.json` in the repo | sharing with the team |

```bash
# Personal setup, all projects
claude mcp add --transport http --scope user <SERVER_NAME> \
  https://<HOST>/<MOUNT>/mcp \
  --header "Authorization: Bearer <api-key>"

# Local development
claude mcp add --transport http --scope local <SERVER_NAME>-dev \
  http://127.0.0.1:8000/<MOUNT>/mcp \
  --header "Authorization: Bearer <api-key>"
```

For a checked-in `.mcp.json`, never write a real key — use env-var expansion so
the committed file stays secret-free:

```bash
claude mcp add --transport http --scope project <SERVER_NAME> \
  https://<HOST>/<MOUNT>/mcp \
  --header "Authorization: Bearer \${<SERVER_NAME_UPPER>_MCP_API_KEY}"
```

Each developer exports their own key before starting Claude Code:

```bash
export <SERVER_NAME_UPPER>_MCP_API_KEY=<api-key>
```
