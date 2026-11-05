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

## Rôles utilisateur
Deux rôles, stockés dans le claim `role` du jeton Firebase / Identity Platform :

| Rôle | Valeur du claim | Remarque |
|---|---|---|
| Client VTC classique | `client-vtc-classique` | rôle **par défaut** (aussi si le claim est absent) |
| Taxi | `taxi` | jamais attribué automatiquement : donné par un admin |

Endpoints (`main.py`, `auth.py`, `roles.py`) :
- `GET /me` : jeton Firebase valide requis (`Authorization: Bearer <idToken>`), renvoie `uid`, `role`, `phone_number`.
- `GET /taxi/ping` : réservé au rôle `taxi` (401 sans jeton, 403 pour un autre rôle). Exemple de route protégée.
- `POST /admin/users/<uid>/role` avec `{"role": "taxi"}` : attribue un rôle. Le service est **privé** sur Cloud Run : seuls les appelants avec `roles/run.invoker` y accèdent. Les anciens jetons sont révoqués ; l'utilisateur doit se reconnecter (ou `getIdToken(true)`) pour voir son nouveau rôle.

Pour les tests : `python test_roles.py` (Firebase simulé, aucun appel réseau).

À prévoir pour l'utiliser en production :
- Le compte de service de Cloud Run doit pouvoir modifier les utilisateurs : rôle `roles/firebaseauth.admin` (changement IAM à faire par un admin du projet).
- Le service est privé : l'app mobile ne peut pas encore appeler `/me`. Il faudra l'ouvrir (`--allow-unauthenticated`, la sécurité reposant alors sur le jeton Firebase, et `/admin/...` à protéger autrement) ou passer par un autre service public.
- Un utilisateur ne doit **jamais** pouvoir choisir lui-même le rôle `taxi`.
