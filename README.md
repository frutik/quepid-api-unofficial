# quepid-api-unofficial
Unofficial API for Quepid. 
Current version of teh API based on Quepid version `7.18.1`
Supposed to be stateless and does not use its own database.

<img width="1142" alt="main" src="https://github.com/user-attachments/assets/a8edc39c-a688-4605-8607-c21d2ebd94ad" />

## Run locally

```
docker compose build
cp .env.example .env
vi .env
docker compose up
```

open in the browser http://127.0.0.1/api/docs

please specify in `.env` correct connection parameters for quepid mysql database

## Deploy to Kubernetes

For now, you need to edit `k8s/deployment.yml` to specify the correct 
connection details for the Quepid MySQL database and 
the desired version to deploy (e.g., v0.2.7). Once 
updated, you can deploy the new version to your cluster.

```
kubectl apply -f k8s/deployment.yml
```

Or

```
cp my_values.yml.example my_values.yml
nano my_values.yml
```

```
helm template charts/quepid-api-unofficial --set appVersion=v0.2.7 --values my_values.yml
```

## Auth

This API uses the same API tokens as the official API. 
To access the endpoints, create an API token as described 
in the official documentation and use it to authorize your 
requests.