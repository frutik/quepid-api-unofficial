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
| Schema `models.py` was generated from | Quepid **v8.1.0** (`schema.rb` version `2025_02_25_162317`) — v8.0.x is column-identical |
| Versions the code runs against cleanly | **v8.0.0 – v8.3.7** |
| First version that breaks it | **v8.4.0** (books lose `selection_strategy_id` *and* `scorer_id`) |
| Version the dev stack starts | **8.3.6** (`docker-compose.yml:77`) |
| Version the `quepid/` submodule is pinned to | `5f53d8f`, 2026-06-23 — **v8.5.0 + 83 commits**, i.e. unreleased 8.6.0 (`schema.rb` version `2026_03_15_000000`) |

Three different versions, then. The dev stack (8.3.6) is inside the supported
range, so local development works. The submodule pin is reference material only
(see `CLAUDE.md`) and is **13 months of schema drift ahead** of the models — do
not read `quepid/db/schema.rb` as a description of the database this code talks
to.

---

## How the baseline was established

`models.py` carries no version marker, so it is dated by bracketing it between
Rails migrations — columns it *has* versus columns it *lacks*:

| Evidence in `models.py` | Migration | Conclusion |
| --- | --- | --- |
| `Users.system_prompt` present | `20250115111655` rename `prompt` → `system_prompt` | after 2025-01-15 |
| no `permissions` table | `20250118025829` drop `permissions` | after 2025-01-18 |
| `CaseScores.scorer_id` present | `20250204192202` add scorer to scores | after 2025-02-04 |
| **no `Users.options`** | `20250310172421` add options to users | before 2025-03-10 |
| column still named `openai_key` (commented out, `models.py:769`) | `20250314170144` rename → `llm_key` | before 2025-03-14 |

That interval contains exactly one schema version, `2025_02_25_162317`, which is
what `git show v8.1.0:db/schema.rb` reports. Table-level check agrees: `models.py`
has `selection_strategies` (dropped in 8.4.0) and lacks `mapper_wizard_states`
(added in 8.4.0).

Columns alone cannot separate v8.1.0 from v8.0.0 / v8.0.1 — the entire
`db/schema.rb` diff between v8.0.0 and v8.1.0 is the version stamp plus one
renamed index on `announcements`. v8.1.0 is simply the newest release that
matches. v7.18.1 and earlier do not: at schema `2024_06_26_181338` the
`permissions` table still exists and `users.system_prompt` is still called
`prompt`, so `Users` reads fail outright.

### Corroboration from this repo's own history

The schema bracketing above is inferred. Git history confirms it directly:

```
caf51b9  2025-05-10  docker-compose.yml pins  o19s/quepid:8.1.0
34e6b32  2026-01-07  docker-compose.yml pins  o19s/quepid:8.3.6
```

For eight months the dev stack ran **exactly 8.1.0** — the version the models
reflect. That is when `inspectdb` was run.

The bump to 8.3.6 is where the drift starts, and commit `34e6b32` shows how it
was handled. Its *entire* change to `models.py` is one line:

```diff
-    openai_key = models.CharField(max_length=255, blank=True, null=True)
+    # openai_key = models.CharField(max_length=255, blank=True, null=True)
```

That is not a cosmetic edit. Quepid renamed `users.openai_key` → `llm_key` in
`20250314170144` (shipped in v8.2.0), so on the newly pinned 8.3.6 every `Users`
read — i.e. every authenticated request — was selecting a column that no longer
existed. Commenting the field out is a **hand-patch standing in for a
regeneration**, and it is the one deviation from the "pure `inspectdb` output"
rule in `CLAUDE.md`. Treat `models.py:769` as a compatibility shim for v8.2.0+,
not as dead code: uncommenting it breaks the app on anything newer than v8.1.0,
and regenerating `models.py` will reintroduce the column under its new name.

### Corroboration from the notebooks

The five notebooks at the repo root (`main.ipynb`, `MMR.ipynb`, `wands.ipynb`,
`qwen-reranker.ipynb`, `qwen-embeddings.ipynb`) each drive a live stack through
this API, and their saved outputs are dated:

| Run (from `created_at` in saved responses) | Quepid then pinned |
| --- | --- |
| 2025-08-14 / 2025-08-15 | 8.1.0 |
| 2026-01-04 / 2026-01-07 | 8.1.0 → 8.3.6 changeover |
| 2026-03-03 | 8.3.6 |

Those runs are the practical evidence for the ✅ rows in the matrix: cases,
queries, ratings, scorers, teams and search endpoints all round-tripped against
8.3.6 with 8.1.0-era models. Two caveats:

- **No notebook ever calls `/api/books`.** The one code path that breaks in
  v8.4.0 is the one path never exercised, so its passing history proves nothing
  about it.
- **The markdown note above the `thor user:add_api_key` cell is stale.** It says
  the command "is only available in nightly build of Quepid" — true when written,
  but the command landed upstream in `09b77445` (2025-07-19) and shipped in
  **v8.2.0**. With the current 8.3.6 pin the caveat no longer applies, matching
  the bootstrap instructions in `CLAUDE.md`, which list it unconditionally.

---

## Compatibility matrix

| Quepid | `schema.rb` version | Status | Notes |
| --- | --- | --- | --- |
| ≤ v7.18.1 | `2024_06_26_181338` | ❌ broken | `users.system_prompt` is still `prompt`; `permissions` table still present |
| v8.0.0 / v8.0.1 | `2025_02_12_153702` | ✅ works | column-identical to the baseline (differs by one index name) |
| **v8.1.0** | `2025_02_25_162317` | ✅ **exact match** | the baseline |
| v8.2.0 / v8.2.1 | `2025_07_09_144954` | ✅ works | `queries.options` and `query_doc_pairs.options` silently became `json` — see [Soft drift](#soft-drift) |
| v8.3.0 – v8.3.7 | `2025_09_30_…` / `2025_10_24_…` | ✅ works | `books.archived` added (`NOT NULL DEFAULT false`, so inserts still succeed); invisible to this API |
| **v8.4.0** | `2026_01_02_125621` | ❌ **broken** | `books.selection_strategy_id` **and** `books.scorer_id` removed, `selection_strategies` table dropped |
| v8.5.0 | `2026_01_14_150154` | ❌ broken | same, plus more additive columns |
| v8.6.0-dev (submodule pin) | `2026_03_15_000000` | ❌ broken | same, plus `search_endpoints.basic_auth_credential` now encrypted at rest |

The matrix above describes the **current** release (v0.8.0). Earlier releases of
this API targeted different Quepid versions — see below.

---

## Our tags vs their tags

`models.py` has been regenerated exactly once in this project's life, so every
release of this API falls into one of four eras:

| Our tags | Released | `models.py` reflects | Compose pins | Runs against |
| --- | --- | --- | --- | --- |
| v0.0.1 – v0.2.11 | 2025-01-18 → 2025-01-25 | Quepid **v7.15.1 / v7.16.0** (`2024_03_08_204637`) | nothing — no Quepid service | v7.15.1 – v7.18.1 |
| v0.3.0 – v0.3.5 | 2025-03-12 → 2025-03-24 | **v8.1.0** — regenerated in `3068d19` | nothing — no Quepid service | v8.0.0 – v8.1.0 |
| v0.3.6 – v0.6.0 | 2025-05-10 → 2025-07-18 | v8.1.0 | **8.1.0** | v8.0.0 – v8.1.0 |
| **v0.6.1 – v0.8.0** (current) | 2026-01-07 → 2026-08-01 | v8.1.0 + the `openai_key` hand-patch | **8.3.6** | **v8.0.0 – v8.3.7** |

Reading the eras:

- **The 7.x era.** The first models were introspected from a Quepid on schema
  `2024_03_08_204637` — `judgements.explanation` present, `users.prompt` /
  `openai_key` and `cases.nightly` absent, `permissions` table still there.
  That is v7.15.1 / v7.16.0 (March 2024). `docker-compose.yml` at v0.3.5 defines
  only `quepid-api-app` and `quepid-api-web`: you brought your own Quepid.
- **`3068d19` "Upgrade to 8.1.0" (2025-03-12)** is the single regeneration —
  +322 lines, new tables (`ahoy_events`, …), two days after v8.1.0 shipped
  (2025-03-10). Every release since inherits it. Its sibling commit `6d79016`
  ("dont mess with introspected models") deleted a hand-added `check_token`
  classmethod from `Users` and is the origin of the "pure `inspectdb` output"
  rule in `CLAUDE.md`.
- **Why v0.6.0 and earlier stop at Quepid v8.1.0.** Those releases declare
  `Users.openai_key`, and `common/auth.py:user_from_token` selects the whole
  `Users` row on **every authenticated request**. Quepid renamed that column to
  `llm_key` in v8.2.0, so v0.6.0 against v8.2.0+ fails at authentication — not in
  some corner of the API, but on all of it.
- **What v0.6.1 bought.** Commenting that one column out extended the range from
  v8.1.0 to v8.3.7 and cost nothing on older versions — a column left out of a
  `SELECT` is harmless — so the current release spans v8.0.0 – v8.3.7. One
  commented line is the whole difference between supporting two Quepid releases
  and supporting seven.

Two footnotes on the tag list: v0.2.12 is dated 2025-03-24 but does **not**
contain `3068d19`, so despite its date it belongs to the 7.x era, not the 8.1.0
one. And the 7.x-era models carry a `Permissions` model for a table Quepid
dropped in v8.0.0 — harmless, because no code of that era ever queried it.

---

## The v8.4.0 break

Two migrations landed in December 2025 and both hit `Books`:

- `20251206163533_remove_selection_strategy_from_books` — drops
  `books.selection_strategy_id` and the whole `selection_strategies` table.
- `20251206221416_add_scale_to_books` — moves `scale` / `scale_with_labels` onto
  `books` and **drops `books.scorer_id`**.

`models.py:255-256` still declares both:

```python
scorer_id = models.IntegerField(blank=True, null=True)
selection_strategy = models.ForeignKey('SelectionStrategies', models.DO_NOTHING)
```

Django puts every declared column in the `SELECT` list, so on a v8.4.0+ database
this fails with `Unknown column 'books.selection_strategy_id' in 'field list'`
before any row is returned. What stops working:

| Surface | Effect |
| --- | --- |
| `GET /api/books`, `GET /api/books/{id}` | 500 / error on every call |
| `POST /api/books` (`api/books.py:48`) | fails — and `CreateBook` *requires* `scorer_id` and `selection_strategy_id`, both of which no longer exist |
| `PATCH /api/books/{id}` | same two fields in `update_fields` |
| MCP `books` toolset (`quepid_mcp/mcp.py:200`) | errors on every query |
| MCP `selection_strategies` toolset (`quepid_mcp/mcp.py:353`) | queries a dropped table |
| Anything traversing `QueryDocPairs.book` with `select_related` | pulls the broken `books` columns in |

`Ratings`, `Judgements`, `Queries`, `Cases`, `Teams`, `Scorers`, `Tries`,
`Snapshots` are unaffected by this particular break.

---

## Soft drift

Changes that do **not** raise today but change behaviour or hide data:

- **`options` columns became MySQL `json` (v8.2.0).** `queries.options` and
  `query_doc_pairs.options` are `TextField` in `models.py`. Reads still return
  the serialized JSON text, so `schemas.py:41 resolve_query_options` keeps
  working, and `api/queries.py:61` writes `json.dumps(...)`, which MySQL accepts.
  The trap is that any *non-JSON* string written to those fields now raises at
  the database instead of being stored.
- **`search_endpoints.basic_auth_credential` is Rails-encrypted (v8.6.0-dev,
  `20260306000002`) and widened to 4000 chars.** `models.py` types it as
  `CharField(max_length=255)`. On such a database this API would return
  ActiveRecord Encryption ciphertext, not the credential — and the MCP
  `searchendpoints` toolset returns the column whether or not it is in `fields`
  (see `docs/mcp-server-plan.md` §3.2).
- **Columns this API cannot see**, because `inspectdb` never captured them:
  `users.options`, `users.llm_key`, `books.archived`, `books.scale`,
  `books.scale_with_labels`, `books.scoring_guidelines`,
  `search_endpoints.requests_per_minute`, `search_endpoints.test_query`,
  `cases.auto_populate_book_pairs`, `cases.auto_populate_case_judgements`, and
  the entire `mapper_wizard_states` table. All are nullable or have defaults, so
  inserts from this API still succeed — the rows just come out with Rails'
  defaults, which for `cases.auto_populate_case_judgements` means `true`.

---

## Re-targeting to a newer Quepid

The regeneration itself is mechanical; the code changes around it are not.

1. Bring up a Quepid of the target version and migrate it, then regenerate —
   `models.py` **must stay pure `inspectdb` output** (`CLAUDE.md`):

   ```bash
   docker compose run quepid-api-quepid bin/rake db:migrate
   docker compose run quepid-api-app \
       python manage.py inspectdb --database quepid > quepid/models.py
   ```

   Regeneration reintroduces the users key column as `llm_key`, undoing the
   hand-comment at `models.py:769`. On v8.2.0+ that is *correct* — the column
   exists again under the new name — but it is also encrypted at rest as of
   `20250709144954`, so decide deliberately whether to keep it out of the model
   rather than surface ciphertext.

2. For v8.4.0+, update the book-shaped code by hand:
   - `api/books.py` — drop `scorer_id` and `selection_strategy_id` from
     `CreateBook`, `UpdateBook`, `create_book` and `update_book`; decide whether
     to expose `scale` / `scale_with_labels` / `scoring_guidelines` instead.
     This is a **breaking change to this API's own contract**, so it wants a
     minor version bump in `package.json`.
   - `quepid_mcp/mcp.py` — delete `SelectionStrategiesToolset` and refresh
     `BooksToolset.fields`.

3. Bump `docker-compose.yml:77` (`o19s/quepid:8.3.6`) to the same version, so
   the dev stack and the models agree.

4. Optionally move the submodule pin to the matching release tag
   (`git -C quepid checkout v8.x.y`, then commit the gitlink), so the vendored
   schema documents the version this code targets rather than upstream `main`.

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
ls db/migrate | awk '$0 > "20250225162317"'
```

Our tags against theirs, one line per release:

```bash
for t in $(git tag -l | sort -V); do
  printf '%s\t%s\t%s\n' "$t" "$(git log -1 --format=%ad --date=short $t)" \
    "$(git show $t:docker-compose.yml 2>/dev/null | grep -o 'o19s/quepid:[0-9.]*')"
done
```

And, from the repo root, the two history checks that dated the baseline
independently of the schema:

```bash
# which Quepid the dev stack has pointed at, over time
git log -p --format='COMMIT %h %ad' --date=short -- docker-compose.yml \
  | grep -E '^COMMIT |^\+.*o19s/quepid'

# when the notebooks last ran against a live stack
grep -ho "'created_at': '20[0-9-]*T[0-9:]*" *.ipynb | sort -u | tail
```

Anything in that last list touching a column present in `models.py` is drift;
anything *removing* one is a break.
