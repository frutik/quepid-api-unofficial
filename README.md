# quepid-api-unofficial
Unofficial API for Quepid


<img width="1142" alt="main" src="https://github.com/user-attachments/assets/a8edc39c-a688-4605-8607-c21d2ebd94ad" />

## Run locally

```
docker compose build
cp .env.example .env
vi .env
docker compose up
```

open in the brovser http://127.0.0.1/api/docs

please specify in `.env` correct connection parameters for quepid mysql database

## Deploy to Kubernetes

For now you should edit `k8s\deployment.yml` specifying correct connection to quepid mysql database 
and desired version to deploy (i.e. `v0.2.7`). After that you can deploy new version to your cluster.

```
kubectl apply -f k8s/deployment.yml
```