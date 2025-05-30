# quepid-api-unofficial
Unofficial API for Quepid. 
Current version of teh API based on Quepid version `7.18.1`
Supposed to be stateless and does not use its own database.

<img width="1142" alt="main" src="https://github.com/user-attachments/assets/a8edc39c-a688-4605-8607-c21d2ebd94ad" />

## Run locally connecting to local Quepid

```
docker compose build
cp .env.example .env
vi .env
docker compose run quepid-api-quepid bin/rake db:migrate
docker compose run quepid-api-quepid bin/rake db:seed
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

## Demo

https://www.youtube.com/watch?v=GIgMtBqzxus
