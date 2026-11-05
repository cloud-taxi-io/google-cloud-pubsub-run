# google-cloud-pubsub-run — API VTC

API **FastAPI** déployée sur **Cloud Run** :
- **Authentification** : Firebase Authentication / Identity Platform (JWT vérifié avec le Firebase Admin SDK à chaque requête).
- **Autorisation (RBAC)** : rôles et permissions dans **PostgreSQL**, seule source de vérité. Aucun *custom claim* Firebase n'est utilisé.
- **GPS des chauffeurs** : les chauffeurs envoient leurs positions, stockées dans **TimescaleDB** (historique) et **PostGIS** (recherche des chauffeurs proches).

## Architecture

```
App mobile ──(Bearer Firebase ID token)──► FastAPI (Cloud Run)
                                              │  1. vérifie le JWT (Firebase Admin SDK)
                                              │  2. charge rôles + permissions (PostgreSQL)
                                              │  3. vérifie la permission de l'endpoint
                                              ▼
POST /v1/drivers/me/locations ──► Pub/Sub (LOCATIONS_TOPIC) ──push OIDC──► POST /pubsub/push
                                              │                                   │
                                              └──── (sans topic : écriture directe)┘
                                                                                  ▼
                                    PostgreSQL : driver_locations (hypertable) + driver_last_locations (PostGIS)
```

Code en couches (`app/`) :

| Dossier | Rôle |
|---|---|
| `core/` | configuration (`pydantic-settings`), logs JSON Cloud Logging, vérification des jetons, codes de permissions |
| `db/` | moteur SQLAlchemy, session par requête |
| `models/` | modèles SQLAlchemy (users, roles, permissions, role_permissions, user_roles) |
| `schemas/` | validation Pydantic des entrées / sorties |
| `repositories/` | accès aux données, sans règle métier |
| `services/` | règles métier (RBAC, ingestion GPS) |
| `api/` | dépendances FastAPI (`get_current_principal`, `require_permissions`) et routes |

## RBAC

Tables : `users`, `roles`, `permissions`, `role_permissions`, `user_roles`. Un utilisateur peut avoir **plusieurs rôles** : ses permissions sont l'union de celles de ses rôles.

Données initiales (migration `0003`) :

| Rôle | Permissions |
|---|---|
| `admin` | toutes (et toute nouvelle permission lui est ajoutée automatiquement) |
| `taxi` | `profile:read`, `location:write` |
| `client-vtc-classique` | `profile:read`, `location:read:nearby` — **rôle par défaut** à la première connexion |

Protéger un endpoint :

```python
from app.api.deps import require_permissions
from app.core.permissions import Perm

@router.post("/me/locations")
def send(batch: LocationBatch, principal: Annotated[Principal, Depends(require_permissions(Perm.LOCATION_WRITE))]): ...
```

- `401` : jeton absent, invalide, expiré ou révoqué.
- `403` : compte désactivé, ou permission manquante.
- Les permissions sont relues **en base à chaque requête** : un changement de rôle ou de permission prend effet immédiatement, **sans redéploiement**.

Règles de sécurité :
- Le rôle `taxi` n'est jamais attribué automatiquement ; seul un admin le donne.
- Les rôles système ne peuvent pas être supprimés ; un rôle encore attribué non plus.
- On ne peut pas retirer le rôle `admin` au dernier admin actif, ni se désactiver soi-même.
- Toutes les modifications RBAC sont journalisées (acteur, cible, rôle / permission).

## Endpoints

| Méthode | Chemin | Permission |
|---|---|---|
| GET | `/v1/me` | `profile:read` |
| POST | `/v1/drivers/me/locations` | `location:write` |
| GET | `/v1/drivers/nearby?lat=&lon=&radius_m=&limit=` | `location:read:nearby` |
| GET | `/v1/drivers/{driver_id}/locations?since=&until=` | `location:read` |
| GET / POST | `/v1/admin/permissions` | `rbac:manage` |
| GET / POST | `/v1/admin/roles` | `rbac:manage` |
| DELETE | `/v1/admin/roles/{role}` | `rbac:manage` |
| PUT / DELETE | `/v1/admin/roles/{role}/permissions/{code}` | `rbac:manage` |
| GET | `/v1/admin/users`, `/v1/admin/users/{id}` | `users:read` |
| PATCH | `/v1/admin/users/{id}` (`is_active`, `display_name`) | `rbac:manage` |
| PUT / DELETE | `/v1/admin/users/{id}/roles/{role}` | `rbac:manage` |
| POST | `/pubsub/push` (et `/`, compatibilité) | jeton OIDC de la subscription Pub/Sub |
| GET | `/healthz`, `/readyz` | — |

## GPS des chauffeurs

Le téléphone envoie des lots (jusqu'à 100 points, pratique hors connexion) :

```json
POST /v1/drivers/me/locations
{"points": [{"recorded_at": "2026-11-05T10:00:00+01:00", "latitude": 36.7538, "longitude": 3.0588,
             "speed_mps": 8.5, "heading_deg": 90, "accuracy_m": 5}]}
```

- L'identifiant du chauffeur vient **toujours du jeton**, jamais du corps de la requête.
- Validation : coordonnées valides, fuseau horaire obligatoire, pas plus de 5 min dans le futur ni plus de 24 h dans le passé.
- Idempotent : un point déjà reçu (même chauffeur, même horodatage) est ignoré. La dernière position ne recule jamais dans le temps.
- Historique conservé **90 jours** (politique de rétention TimescaleDB).
- `/v1/drivers/nearby` ne renvoie que les chauffeurs **actifs** vus dans les **2 dernières minutes**, du plus proche au plus loin.

Avec `LOCATIONS_TOPIC`, l'API publie dans Pub/Sub et répond tout de suite (`"mode": "queued"`) ; la subscription push écrit en base.
Sans topic, l'API écrit directement (`"mode": "stored"`). Les messages invalides sont acquittés et journalisés, les erreurs de base renvoient 500 pour être réessayées.

## Configuration (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `DATABASE_URL` | — (obligatoire) | `postgresql+psycopg://app:<mdp>@<ip>:5432/app` |
| `FIREBASE_PROJECT_ID` | ADC | projet Firebase |
| `FIREBASE_CHECK_REVOKED` | `true` | rejette tout de suite les jetons révoqués (1 appel Google en plus par requête) |
| `DEFAULT_ROLE` | `client-vtc-classique` | rôle des nouveaux utilisateurs |
| `GCP_PROJECT_ID`, `LOCATIONS_TOPIC` | vide | active le mode Pub/Sub |
| `PUBSUB_VERIFY_OIDC` | `true` | vérifie le jeton OIDC des messages push |
| `PUBSUB_AUDIENCE`, `PUBSUB_SERVICE_ACCOUNT` | — | obligatoires si `PUBSUB_VERIFY_OIDC=true` |
| `ENABLE_DOCS` | `false` | expose `/docs` |

## Développement et tests

Les tests utilisent une **vraie** base PostgreSQL + PostGIS + TimescaleDB ; seul Firebase est simulé.

```bash
docker run -d --name vtc-test-db -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=test timescale/timescaledb-ha:pg17
pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+psycopg://postgres:test@127.0.0.1:55432/postgres pytest -q
```

Migrations :

```bash
DATABASE_URL=... alembic upgrade head
DATABASE_URL=... alembic revision --autogenerate -m "..."
```

Premier admin (l'API admin demande déjà un admin) :

```bash
DATABASE_URL=... python -m app.cli grant-role <firebase_uid> admin --create
```

## Déploiement

Non automatisé dans ce dépôt. Points à régler côté infrastructure (dépôt `google-cloud-infra-manager`) :
1. **Accès à la base** : PostgreSQL tourne sur la VM `timescaledb` et n'écoute qu'en local. Il faut un utilisateur `app` avec mot de passe (Secret Manager), l'écoute sur l'IP interne, `pg_hba.conf`, une règle de pare-feu, et le **Direct VPC egress** de Cloud Run vers le réseau de la VM. La VM est dans `us-central1` et Cloud Run dans `europe-west1` : mieux vaut les rapprocher.
2. **Cloud Run public** (`--allow-unauthenticated`) : l'app mobile envoie un jeton Firebase, pas un jeton IAM. La sécurité repose alors sur la vérification du JWT et sur le RBAC, et `/pubsub/push` sur le jeton OIDC (`PUBSUB_AUDIENCE` = URL du service, `PUBSUB_SERVICE_ACCOUNT` = `pubsub-invoker@...`).
3. **Migrations** dans un Cloud Run job (`alembic upgrade head`) avant chaque déploiement.
4. Subscription push vers `<URL>/pubsub/push` (l'ancien chemin `/` reste accepté).
