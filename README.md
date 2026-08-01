# quepid-api-unofficial
Unofficial API for Quepid. 
Current version of teh API based on Quepid version `7.18.1`
Supposed to be stateless and does not use its own database.

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
your Quepid data directly. It exposes 14 collections — `cases`, `queries`,
`ratings`, `books`, `querydocpairs`, `judgements`, `tries`, `snapshots`,
`snapshotqueries`, `searchendpoints`, `scorers`, `selectionstrategies`, `teams`
and `teamscases` — queried with a MongoDB-style aggregation pipeline
(`$match`, `$lookup`, `$sort`, `$project`, `$group`, `$limit`).

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