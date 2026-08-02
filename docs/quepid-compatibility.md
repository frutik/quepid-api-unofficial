# Quepid compatibility

Which versions of Quepid this API actually works against, and what breaks where.

This project has no schema of its own: `quepid_api/quepid/models.py` is
`inspectdb` output taken from a Quepid database at one point in time, and Rails
keeps migrating that schema underneath us. So "which Quepid version is this
based on" has a precise answer — the one whose `db/schema.rb` version matches
the columns in `models.py` — and a second, less comfortable one: the range of
Quepid versions the code still runs against.

---

## Summary

| Question | Answer |
| --- | --- |
| Schema `models.py` was generated from | Quepid **v8.5.0** (`schema.rb` version `2026_01_14_150154`) |
| Versions the code runs against cleanly | **v8.4.0 – v8.5.0** |
| Last version that breaks it | **v8.3.7** and older (books have no `scale`; `mapper_wizard_states` absent) |
| Version the dev stack starts | **8.5.0** (`docker-compose.yml:77`) |
| Version the `quepid/` submodule is pinned to | **v8.5.0** (`1ba948d7`) |

All four now agree. That is new: before the v8.5.0 upgrade the models reflected
v8.1.0, the dev stack ran 8.3.6 and the submodule pointed at an unreleased
8.6.0-dev, so `quepid/db/schema.rb` described none of them. It is now a faithful
description of the database this code talks to.

The supported range is **narrow and has moved up, not widened**. v8.4.0 is a
hard floor: `models.py` declares `books.scale`, `books.scale_with_labels` and
`books.scoring_guidelines`, which do not exist before it. This release does
**not** run against v8.3.x — see [Our tags vs their tags](#our-tags-vs-their-tags).

---

## Hand-patches carried across regenerations

`CLAUDE.md` requires `models.py` to stay pure `inspectdb` output. In practice
three deliberate deviations have accumulated, each one load-bearing, and **a
regeneration silently drops all three**. That is the single most dangerous step
in re-targeting this project, so they are listed here rather than left to be
rediscovered from `git log`.

| Field | Change | Origin | Why it is needed |
| --- | --- | --- | --- |
| `SearchEndpoints.owner` | `owner_id` IntegerField → `ForeignKey('Users')` | `989b68d` | `api/search_endpoints.py:60` assigns `owner=request.auth`, a `Users` *instance* |
| `Tries.search_endpoint` | `search_endpoint_id` BigIntegerField → `ForeignKey('SearchEndpoints')` | `05ece2d` | `api/cases.py:102` assigns an instance; `quepid_mcp/mcp.py` publishes it as a real reference |
| `CaseScores.queries` | `TextField` → `BinaryField` | `381ff88` | the column is `mediumblob`; `inspectdb` guesses `TextField` for blobs |

Neither FK exists as a database constraint — `tries` carries only
`tries_ibfk_1` on `case_id`, and `search_endpoints` has none at all — so
`inspectdb` has no way to infer them and emits plain integer fields every time.
Reverting either one reintroduces the same class of bug `tests/test_books.py:37`
documents for books: passing a model instance into an `IntegerField`, which
Django cannot adapt, failing inside a broad `except Exception` as a bare 400.

A fourth hand-patch has now **retired**: `34e6b32` commented out
`Users.openai_key` as a shim for v8.2.0+, where Rails renamed the column to
`llm_key`. Regenerating against v8.5.0 brings it back correctly named, so the
comment is gone. `llm_key` is Rails-encrypted at rest, but `Users` is published
nowhere — no schema, no router, no MCP toolset — so no client ever sees the
ciphertext.

A fifth, `6d79016`, removed a hand-added `ApiKeys.check_token` classmethod and
is the origin of the pure-`inspectdb` rule. Do not reintroduce it.

**After every regeneration, verify with:**

```bash
git diff quepid_api/quepid/models.py \
  | grep -E '^[-+].*(owner|search_endpoint|queries) = '
```

Three deletions with no matching additions means the patches were dropped.

---

## Compatibility matrix

| Quepid | `schema.rb` version | Status | Notes |
| --- | --- | --- | --- |
| ≤ v8.3.7 | ≤ `2025_10_24_…` | ❌ broken | `books.scale` / `scale_with_labels` / `scoring_guidelines` do not exist yet; every books endpoint fails in the SELECT list |
| **v8.4.0** | `2026_01_02_125621` | ✅ works | first version with the post-`selection_strategies` books shape |
| **v8.5.0** | `2026_01_14_150154` | ✅ **exact match** | the baseline, and what the dev stack and submodule pin run |
| v8.6.0-dev | `2026_03_15_000000` | ⚠️ untested | `search_endpoints.basic_auth_credential` becomes encrypted and widens to 4000 chars — see [Soft drift](#soft-drift) |

The matrix describes the **current** release. Earlier releases targeted
different Quepid versions — see below.

---

## Our tags vs their tags

`models.py` has been regenerated twice in this project's life, so every release
falls into one of five eras:

| Our tags | Released | `models.py` reflects | Compose pins | Runs against |
| --- | --- | --- | --- | --- |
| v0.0.1 – v0.2.11 | 2025-01-18 → 2025-01-25 | Quepid **v7.15.1 / v7.16.0** (`2024_03_08_204637`) | nothing — no Quepid service | v7.15.1 – v7.18.1 |
| v0.3.0 – v0.3.5 | 2025-03-12 → 2025-03-24 | **v8.1.0** — regenerated in `3068d19` | nothing — no Quepid service | v8.0.0 – v8.1.0 |
| v0.3.6 – v0.6.0 | 2025-05-10 → 2025-07-18 | v8.1.0 | **8.1.0** | v8.0.0 – v8.1.0 |
| v0.6.1 – v0.8.2 | 2026-01-07 → 2026-08-02 | v8.1.0 + the `openai_key` hand-patch | **8.3.6** | v8.0.0 – v8.3.7 |
| **v0.9.0** (current) | 2026-08-02 | **v8.5.0** — regenerated | **8.5.0** | **v8.4.0 – v8.5.0** |

Reading the eras:

- **The 7.x era.** The first models were introspected from a Quepid on schema
  `2024_03_08_204637` — `judgements.explanation` present, `users.prompt` /
  `openai_key` and `cases.nightly` absent, `permissions` table still there.
  That is v7.15.1 / v7.16.0 (March 2024). `docker-compose.yml` at v0.3.5 defines
  only `quepid-api-app` and `quepid-api-web`: you brought your own Quepid.
- **`3068d19` "Upgrade to 8.1.0" (2025-03-12)** was the first regeneration —
  +322 lines, new tables (`ahoy_events`, …), two days after v8.1.0 shipped.
- **Why v0.6.0 and earlier stop at Quepid v8.1.0.** Those releases declare
  `Users.openai_key`, and `common/auth.py:user_from_token` selects the whole
  `Users` row on **every authenticated request**. Quepid renamed that column to
  `llm_key` in v8.2.0, so v0.6.0 against v8.2.0+ fails at authentication — not in
  some corner of the API, but on all of it.
- **What v0.6.1 bought.** Commenting that one column out extended the range from
  v8.1.0 to v8.3.7 and cost nothing on older versions — a column left out of a
  `SELECT` is harmless. One commented line was the whole difference between
  supporting two Quepid releases and supporting seven.
- **Why v0.9.0 does not span both sides.** The v8.4.0 books migrations both
  *dropped* and *added* columns, so no single set of `inspectdb` output satisfies
  v8.3.x and v8.4.0+ at once. The `openai_key` trick worked because a missing
  column can simply be left out of the model; a column that must be *present*
  on one side and *absent* on the other has no such escape. Pick a side.

Two footnotes on the tag list: v0.2.12 is dated 2025-03-24 but does **not**
contain `3068d19`, so despite its date it belongs to the 7.x era. And the 7.x-era
models carry a `Permissions` model for a table Quepid dropped in v8.0.0 —
harmless, because no code of that era ever queried it.

---

## What the v8.4.0 / v8.5.0 upgrade changed here

Beyond the books columns, regenerating against v8.5.0 moved four things that
needed code changes rather than just a new model file:

- **`queries.options` and `query_doc_pairs.options` are now `JSONField`.** They
  became MySQL `json` back in v8.2.0, but the old `models.py` still typed them
  as `TextField`, so `api/queries.py` wrote `json.dumps(...)` by hand. Against a
  real `JSONField` that **double-encodes**: Django serializes the string, and
  the column ends up holding a JSON *string* where Quepid expects an object.
  Both write sites now pass the dict straight through.
  `tests/test_queries.py:58` explains why the HTTP suite cannot catch this —
  `resolve_query_options` falls back to `json.loads` and silently recovers, so
  the REST response is byte-identical either way. Verify by reading the column:

  ```sql
  SELECT JSON_TYPE(options) FROM queries WHERE id = <id>;   -- want OBJECT, not STRING
  ```

- **`books.archived` is `NOT NULL`** (added v8.3.0) and `inspectdb` gives it no
  Django default, so `Books.objects.create(...)` sent `NULL` and MySQL rejected
  it with `Column 'archived' cannot be null`. `api/books.py:create_book` now
  passes `archived=0` explicitly — the same pattern `created_at` / `updated_at`
  already required, and the reason every books test failed on first run.

- **The `teams_*` junction tables now use `CompositePrimaryKey`.** Modern
  `inspectdb` emits `pk = models.CompositePrimaryKey('case_id', 'team_id')`
  instead of the old "composite primary key found, that is not supported"
  `OneToOneField` workaround. This needs Django ≥ 5.2; the app image runs 6.0.
  Nothing writes to these tables — MCP only reads them for scoping — so the
  change is read-only in effect.

- **`cases.options`, `search_endpoints.options` and `users.options` became
  `JSONField` too.** `api/cases.py:141` assigns a dict to `case.options`, which
  was silently storing a Python `repr` into a `TextField` before and is now
  correct.

---

## Soft drift

Changes that do **not** raise today but change behaviour or hide data:

- **`search_endpoints.basic_auth_credential` is Rails-encrypted as of
  v8.6.0-dev** (`20260306000002`) and widened to 4000 chars. At v8.5.0 it is
  still a plain `varchar(255)`, which is what `models.py` reflects. On a
  v8.6.0 database this API would return ActiveRecord Encryption ciphertext
  rather than the credential — and the MCP `searchendpoints` toolset returns the
  column whether or not it is in `fields` (see `docs/mcp-server-plan.md` §3.2).
- **Columns this API cannot see** because they postdate the baseline: anything
  added after `2026_01_14_150154`. At the time of writing that is the
  v8.6.0-dev set only.
- **`cases.auto_populate_book_pairs` / `auto_populate_case_judgements`** are now
  captured by `inspectdb`, but nothing in this API sets them, so inserts still
  take Rails' defaults — which for `auto_populate_case_judgements` means `true`.

---

## Re-targeting to a newer Quepid

The regeneration itself is mechanical; the code changes around it are not.

1. Bring the stack up on the target version and migrate it:

   ```bash
   # docker-compose.yml: o19s/quepid:<target>
   docker compose up -d quepid-api-quepid
   docker compose exec -T quepid-api-quepid bin/rake db:migrate
   ```

   Confirm the database actually moved — this is the check that catches "I edited
   the tag but the container never restarted":

   ```sql
   SELECT MAX(version) FROM schema_migrations;   -- must equal the target's schema.rb
   ```

2. Regenerate, then **re-apply the three hand-patches above**:

   ```bash
   docker compose exec -T quepid-api-app \
       python manage.py inspectdb --database quepid > quepid_api/quepid/models.py
   ```

3. Diff the table sets and the field list; anything *removed* is a break,
   anything whose *type* changed is potential soft drift:

   ```bash
   git diff -U0 quepid_api/quepid/models.py | grep -E '^[-+]    [a-z_]+ = '
   ```

   Pay particular attention to `TextField` → `JSONField` flips: they do not
   raise, they corrupt.

4. Fix every `NOT NULL` column that `inspectdb` gives no default. Django omits
   nothing from an INSERT, so each one needs an explicit value at the `.create()`
   site (`created_at`, `updated_at`, `books.archived` today).

5. Rebuild the app image — the code is baked in, not mounted, so edits are
   invisible until you do:

   ```bash
   docker compose build quepid-api-app && docker compose up -d quepid-api-app
   ```

6. Move the submodule pin to the matching release tag so the vendored schema
   documents the version this code targets:

   ```bash
   git -C quepid checkout v8.x.y   # then commit the gitlink
   ```

7. Run the suite against the new stack, declaring the version:

   ```bash
   export QUEPID_API_TOKEN=$(docker compose exec -T quepid-api-quepid \
       bundle exec thor user:add_api_key admin@example.com | grep -o '[0-9a-f]\{64\}')
   export QUEPID_TARGET=8.x.y
   pytest
   ```

   `QUEPID_TARGET` is not cosmetic: `tests/test_books.py:52` asserts in both
   directions, so it fails if the database disagrees with what you declared.

8. If the API's own request contract changed, bump `package.json` — it is the
   source of truth for the released version.

---

## Re-running this audit

The whole check is a diff between `models.py` and the vendored `schema.rb`:

```bash
# tables: Django side vs Rails side
grep -o "db_table = '[a-z_]*'" quepid_api/quepid/models.py | cut -d"'" -f2 | sort > /tmp/dj.txt
grep -o 'create_table "[a-z_]*"' quepid/db/schema.rb        | cut -d'"' -f2 | sort > /tmp/rails.txt
comm -3 /tmp/dj.txt /tmp/rails.txt

# schema version each release shipped
cd quepid
for t in $(git tag -l 'v8*' | sort -V); do
  echo "$t $(git show $t:db/schema.rb | grep -m1 -o 'version: [0-9_]*')"
done

# migrations applied after the baseline
ls db/migrate | awk '$0 > "20260114150154"'
```

Our tags against theirs, one line per release:

```bash
for t in $(git tag -l | sort -V); do
  printf '%s\t%s\t%s\n' "$t" "$(git log -1 --format=%ad --date=short $t)" \
    "$(git show $t:docker-compose.yml 2>/dev/null | grep -o 'o19s/quepid:[0-9.]*')"
done
```

And, from the repo root, the history check that dates the baseline
independently of the schema:

```bash
# which Quepid the dev stack has pointed at, over time
git log -p --format='COMMIT %h %ad' --date=short -- docker-compose.yml \
  | grep -E '^COMMIT |^\+.*o19s/quepid'
```

Anything in that last list touching a column present in `models.py` is drift;
anything *removing* one is a break.
