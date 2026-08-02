# quepid-api-unofficial

An unofficial API for [Quepid](https://github.com/o19s/quepid), in two surfaces:

- an **HTTP API** described by **OpenAPI 3.1**, browsable at `/api/docs`
- a read-only **MCP server** at `/mcp/mcp`, publishing 13 collections to LLM
  clients

Both accept the same bearer tokens as the official Quepid API. The app is
stateless: it has no database of its own, and reads and writes the MySQL schema
that the Rails Quepid app owns and migrates.

It also ships [three commands](#commands) that build a Quepid case out of a
public relevance dataset — WANDS or ESCI — downloading it for you, so there is
something real to measure against within a minute of starting the stack.

## Quepid compatibility

**Pick the release that matches your Quepid.** This app reflects Quepid's
Rails-owned schema, so each release only runs against the Quepid versions whose
schema it was generated from.

| This API | Quepid | |
| --- | --- | --- |
| **v0.9.0** — unreleased, `main` | **8.4.0 – 8.5.0** | built against 8.5.0 |
| **v0.8.2** — latest release | **8.0.0 – 8.3.7** | built against 8.1.0 |
| v0.3.6 – v0.6.0 | 8.0.0 – 8.1.0 | |
| v0.0.1 – v0.2.11 | 7.15.1 – 7.18.1 | |

The two current lines do **not** overlap, and cannot: v8.4.0 both dropped and
added `books` columns, so `main` fails on Quepid 8.3.7 and older, and v0.8.2's
books endpoints fail on 8.4.0 and newer. Pick a side.

Full version matrix, the evidence behind it and what to change when
re-targeting: [`docs/quepid-compatibility.md`](docs/quepid-compatibility.md).

<img width="1142" alt="main" src="https://github.com/user-attachments/assets/a8edc39c-a688-4605-8607-c21d2ebd94ad" />

## Clone

Quepid itself is vendored as a git submodule in `quepid/`, for reference to the
database schema this API reads and writes. Clone with submodules:

```
git clone --recurse-submodules git@github.com:frutik/quepid-api-unofficial.git
```

If you already cloned without it, `quepid/` will be an empty directory — fill it
in with:

```
git submodule update --init
```

Nothing in the API imports from `quepid/`, so it is not required to run the app;
it is there to read.

## Run locally connecting to local Quepid

```
docker compose build
cp .env.example .env
vi .env
docker compose run quepid-api-quepid bin/rake db:migrate
docker compose run quepid-api-quepid bin/rake db:seed
docker compose run quepid-api-quepid bundle exec thor user:create -a admin@example.com "Admin User" supersecret
docker compose run quepid-api-quepid bundle exec thor user:add_api_key admin@example.com
```

Store api key created by a command above

```
docker compose up
```


open in the browser

- for api: http://localhost:8081/api/docs
- for quepid: http://localhost:3000/

## Run locally connecting to your self-hosted Quepid

please specify in `.env` correct connection parameters for quepid mysql database

## Commands

Three Django management commands come with the app. Together they turn a public
relevance dataset into a working Quepid case — so you can compare query DSLs
against real judgements instead of hand-typing queries and rating them yourself.
It is what [`wands.ipynb`](wands.ipynb) does, as commands.

| | |
| --- | --- |
| [`create_case <name>`](#create_case) | an empty case — query DSL, field spec, and optionally the search endpoint |
| [`load_dataset <dataset> <case id>`](#load_dataset) | that dataset's queries and judgements, into an existing case |
| [`list_cases`](#list_cases) | which cases exist, and which are already filled |

They are **clients of this API over HTTP**, like anything else you would write
against it — so they need a running stack and a token, not database credentials,
and they work against any deployment, not only a local one. (A side effect worth
knowing: one load puts a few hundred thousand calls through the whole request
path, which is coverage the test suite never reaches.)

```
export QUEPID_API_TOKEN=<your api token>       # thor user:add_api_key
cd quepid_api

./manage.py create_case "wands baseline" \
  --search-fields "name,description" \
  --field-spec "id:_id, title:name" \
  --endpoint-url http://quepid-api-elasticsearch:9200/wands/_search
# Created search endpoint 12 at http://quepid-api-elasticsearch:9200/wands/_search.
# Created case 77 "wands baseline".
# Fill it: manage.py load_dataset <dataset> 77

./manage.py load_dataset wands 77
# Loading into case 77 "wands baseline".
# Downloading query.csv from https://raw.githubusercontent.com/wayfair/WANDS/...
# Reading wands from /tmp/app/quepid-datasets/wands ...
# 480 queries, 231873 judgements
#   480/480 queries
#   231873/231873 ratings
# Case 77: 480 queries, 231873 ratings.

./manage.py list_cases
#     ID  NAME                                          SCORER  TRIES  QUERIES
#     77  wands baseline                                     1      1      480
```

Every command takes `--api-url` (defaults to `QUEPID_API_URL`, then
`http://localhost:8081/api`), `--api-token` (defaults to `QUEPID_API_TOKEN`) and
`--timeout`. Anything they create is owned by whoever the token belongs to.

Inside the Compose stack, run them in the **running** app container so the
download cache survives between commands:

```
docker compose exec \
  -e QUEPID_API_TOKEN -e QUEPID_API_URL=http://localhost/api \
  quepid-api-app python manage.py load_dataset wands 77
```

A `docker compose run --rm` works too, but each one gets a fresh `/tmp/app` and
downloads the dataset again. The app image bakes the code in, so
`docker compose build quepid-api-app` first if you have changed it.

### Datasets

Two ship with the commands, and **you download neither** — `load_dataset` fetches
what it needs from GitHub on first use:

| | |
| --- | --- |
| **wands** | [Wayfair WANDS](https://github.com/wayfair/WANDS/tree/main/dataset) — 480 product queries, 231873 judgements. `query.csv` + `label.csv`, 6 MB |
| **esci** | [Amazon ESCI](https://github.com/amazon-science/esci-data/tree/main/shopping_queries_dataset) — 8956 queries, 181701 judgements, the US small-version test split. `shopping_queries_dataset_examples.parquet`, 51 MB |

Labels become ratings on a 0–3 scale: WANDS' Exact/Partial/Irrelevant as 3/2/0,
ESCI's Exact/Substitute/Complement/Irrelevant as 3/2/1/0. Judgements are keyed by
the dataset's own document ids — WANDS product ids, ESCI ASINs — so they score
something only if your index uses those ids too (if it does not, see
`--doc-id-map` below).

Neither **corpus** is downloaded: 90 MB of WANDS products and the ESCI-S
metadata belong in your search engine, and Quepid stores queries and judgements,
never documents. Indexing them is a separate step, and the notebooks at the repo
root do it.

Downloads go to `$TMP_DIR/quepid-datasets/<dataset>/` (`/tmp/app/…` in the app
image), so the ESCI parquet is fetched once. Delete that directory to
re-download; set `TMP_DIR` yourself to keep the cache somewhere permanent. ESCI
is parquet, so it needs `pyarrow` — in `requirements.txt`, but **rebuild the app
image** if you are running inside Compose.

### create_case

Creates the case and its try, and — with `--endpoint-url` — the search endpoint
too. A case that can actually run needs an endpoint: either one you already have
(`--search-endpoint-id`) or one created for you, at a URL reachable **from
Quepid**, not from you.

**It takes no dataset.** A case is a search configuration — a DSL, a field spec,
a scorer, somewhere to send the query — and none of that follows from which
judgements you are about to load into it. Everything comes from the flags below,
so the same WANDS judgements can go into cases pointed at whatever you have
indexed, however you indexed it.

| | |
| --- | --- |
| `--search-fields "name^2,description"` | fields for the default `multi_match` DSL. Default: `*` |
| `--search-query-file q.json` | a DSL of your own instead, e.g. the reranked variants from the notebooks. Must contain `#$query##`, which Quepid replaces with each query |
| `--field-spec "id:_id, title:name"` | how a hit becomes a displayable document. Default: `id:_id`, Quepid's own |
| `--endpoint-url` / `--search-endpoint-id` | create an endpoint for the case, or point it at an existing one |
| `--endpoint-name` / `--search-engine` / `--api-method` / `--proxy-requests` | how a created endpoint is configured. Defaults: the case name, `es`, `POST`, `1` |
| `--mapper-code-file m.js` | JavaScript mapping a response Quepid cannot read by itself, for `--search-engine searchapi` |
| `--scorer nDCG@10` / `--scorer-id` | scorer for the case. The name is *resolved*, never left to the API's default of id 5 |
| `--dry-run` | resolve everything, write nothing |

### load_dataset

Posts the queries and their judgements into a case that already exists. It takes
the dataset name and the case id and **nothing about files** — it downloads what
it needs.

| | |
| --- | --- |
| `--limit 5` | load only the first N queries. Makes a smoke test cheap |
| `--skip-ratings` | queries only, no judgements |
| `--append` | load into a case that already has queries |
| `--query-options-file f.json` | per-query options, e.g. a vector (see below) |
| `--doc-id-map f.json` | translate the dataset's document ids (see below) |
| `--workers 8` | concurrent rating posts. `1` matches the notebooks |
| `--dry-run` | read and resolve everything, write nothing |

`create_case` never loads data and `load_dataset` never creates a case: a dataset
can go into a case you built in Quepid's UI, and re-running a load cannot quietly
leave you with two cases. Loading into a case that already has queries is refused
unless you pass `--append`, because nothing about a query is unique — a second
load would double every query and judgement rather than update them.

> ⚠️ A load is **not atomic** — there is no bulk endpoint, so it is one request
> per row. A failure part-way leaves the case half-filled; the error says so.

### list_cases

Ids, names, scorer, tries and query count, newest first — the query count being
how you tell a filled case from an empty one.

| | |
| --- | --- |
| `--archived` | archived cases instead of active ones. `DELETE /api/case/{id}/` is a soft delete, so this is where deleted cases went |
| `--search TEXT` | only cases whose name contains this |
| `--limit 50` | how many to show. `0` for all |
| `--no-counts` | skip the query count, which costs one request per case listed |

### Image search in Qdrant

The case from [*How to evaluate image search in Qdrant using
Quepid*](https://frutik.medium.com/how-to-evaluate-image-search-in-qdrant-using-quepid-and-the-hacks-it-takes-part-1-f8167ec5cba3)
is `create_case` flags: a `searchapi` endpoint with the article's response mapper
(shipped as
[`quepid_datasets/mappers/qdrant.js`](quepid_api/quepid_datasets/mappers/qdrant.js)),
the `{"vector": "#$qOption.clip##", …}` DSL, and thumbnails in the results.

Two things no dataset can provide, because both are created when *you* index the
corpus:

- `--query-options-file` — the CLIP vector for each query, as
  `{"laptop stand": {"clip": [0.1, …]}}`. It lands in the query's options, where
  `#$qOption.clip##` picks it up.
- `--doc-id-map` — dataset ids to the ids your engine returns, as
  `{"B07XYZ": 41}`. Qdrant point ids are assigned at index time and are not
  ASINs, so without this every judgement scores nothing. Unmapped ones are
  dropped and counted.

```
echo '{"vector": "#$qOption.clip##", "limit": 30, "with_payload": true}' > qdrant.json

./manage.py create_case "images search" \
  --search-query-file qdrant.json \
  --field-spec "id,title,thumb:thumb" \
  --search-engine searchapi \
  --mapper-code-file quepid_datasets/mappers/qdrant.js \
  --proxy-requests 0 \
  --endpoint-url http://localhost:6333/collections/esci/points/search

./manage.py load_dataset esci 78 \
  --query-options-file clip_vectors.json \
  --doc-id-map point_ids.json
```

Both flags work with any dataset — `--query-options-file` is the general way to
put anything into a query's options.

## Tests

The tests drive the API over HTTP, so they need the stack from
"Run locally" above already running. They never import Django.

> ⚠️ **They write to whatever database you point them at** — creating and
> deleting teams, scorers, search endpoints, cases, queries, ratings and books.
> Use a throwaway stack, never a Quepid whose data you care about.

`docker-compose.yml` pins published image tags alongside `build:`, so build
first or you will be testing the last release instead of your working copy:

```
docker compose build
docker compose up -d
```

Then point the tests at it. `QUEPID_API_TOKEN` is the key from
`thor user:add_api_key`; `QUEPID_TARGET` is the Quepid version the stack runs
(`docker-compose.yml`), which selects the expected `/api/books` shape across the
v8.4.0 schema change.

```
export QUEPID_API_TOKEN=<your api token>
export QUEPID_TARGET=8.5.0
npm test
```

`QUEPID_MEMBER_API_TOKEN` is optional and only affects `tests/test_mcp.py`. MCP
scopes rows to the token owner, but Quepid administrators bypass that scoping,
so the three scoping tests need a key belonging to a **non-admin** account or
they would pass whether or not scoping works. They skip when it is unset:

```
export QUEPID_MEMBER_API_TOKEN=<key for a non-admin user>
```

Just one module:

```
npm run test:books
npm run test:mcp
```

Nothing here fails for want of a stack. With no `QUEPID_API_TOKEN` the
authenticated tests skip and only the handful checking that endpoints reject
unauthenticated calls still run; with nothing listening at all, every test skips.

`DELETE /api/case/{id}/` is a soft delete, so each run leaves its cases behind
with `archived = 1`. They are hidden from `GET /api/case/` by default; see
`tests/conftest.py` for the sweep query.

## Deploy to Kubernetes

Create and edit a file with the variables specific for your environment (specify the correct 
connection details for the Quepid MySQL)

```
cp my_values.yml.example my_values.yml
vi my_values.yml
```

Generate Kubernetes manifests

> Don't forget to specify desired version for deploy (e.g., `v0.2.7`).

> Checkout this repository first.

```
helm template charts/quepid-api-unofficial --set appVersion=v0.2.7 --values my_values.yml > manifests.yml
```

Review them

```
less manifests.yml
```

Deploy to your Kubernetes cluster

```
kubectl apply -f manifests.yml
```

## Auth

This API uses the same API tokens as the official API. 
To access the endpoints, create an API token as described 
in the official documentation and use it to authorize your 
requests.

## MCP server

Alongside the REST API this project serves a read-only
[MCP](https://modelcontextprotocol.io) endpoint, so an AI assistant can query
your Quepid data directly. It exposes 13 collections — `cases`, `queries`,
`ratings`, `books`, `querydocpairs`, `judgements`, `tries`, `snapshots`,
`snapshotqueries`, `searchendpoints`, `scorers`, `teams`
and `teamscases` — queried with a MongoDB-style aggregation pipeline
(`$match`, `$lookup`, `$sort`, `$project`, `$group`, `$limit`).

https://www.youtube.com/watch?v=vcgjahwHSko

Endpoint (note the doubled path segment):

```
http://localhost:8081/mcp/mcp
```

**It uses the same API token as everything else here** — the one issued by
Quepid with `thor user:add_api_key`. There is no separate credential to manage,
and no extra setup: the endpoint is live as soon as the app is running.

Results are read-only and scoped to the token's owner and the teams they belong
to, so an assistant only ever sees what that user could see in Quepid itself.
An empty result means the data is not shared with you, not that it is missing.
Quepid administrators see everything.

### Add it to Claude Code

```
claude mcp add --transport http --scope user quepid \
  http://localhost:8081/mcp/mcp \
  --header "Authorization: Bearer <your-api-token>"
```

Then check it connected:

```
claude mcp list
```

For a self-hosted deployment swap in your own host. To share the config with
your team instead, this repo already ships a `.mcp.json` that reads the token
from the environment, so no secret is committed — each developer just exports
their own before starting Claude Code:

```
export QUEPID_MCP_API_KEY=<your-api-token>
```


## Demo

https://www.youtube.com/watch?v=GIgMtBqzxus


```
docker run --rm \
  -v ${PWD}:/local openapitools/openapi-generator-cli generate \
  -i https://shopnest.webshop.nl/api/openapi.json \
  -g python \
  --skip-validate-spec \
  --additional-properties=licenseName=MIT \
  -o /local/shopnest-client
  ```