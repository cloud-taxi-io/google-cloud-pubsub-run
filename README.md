# google-cloud-pubsub-run

Petit service Flask déployé sur **Cloud Run**, qui reçoit des messages **Pub/Sub** via une subscription push authentifiée (OIDC).

## Architecture

```
Pub/Sub topic (mon-topic) -> subscription push (ma-sub) -> Cloud Run (mon-service)
```

## Déploiement

```bash
export PROJECT=<votre-id-projet>
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com pubsub.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

gcloud pubsub topics create mon-topic
gcloud run deploy mon-service --source . --region europe-west1 --no-allow-unauthenticated

gcloud iam service-accounts create pubsub-invoker
gcloud run services add-iam-policy-binding mon-service --region europe-west1 \
  --member=serviceAccount:pubsub-invoker@$PROJECT.iam.gserviceaccount.com --role=roles/run.invoker

# L'agent de service Pub/Sub doit pouvoir créer des jetons OIDC
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
gcloud iam service-accounts add-iam-policy-binding pubsub-invoker@$PROJECT.iam.gserviceaccount.com \
  --member=serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com \
  --role=roles/iam.serviceAccountTokenCreator

gcloud pubsub subscriptions create ma-sub --topic mon-topic \
  --push-endpoint=<URL_CLOUD_RUN> \
  --push-auth-service-account=pubsub-invoker@$PROJECT.iam.gserviceaccount.com
```

## Test

```bash
gcloud pubsub topics publish mon-topic --message "hello"
gcloud run services logs read mon-service --region europe-west1 --limit 10
```
