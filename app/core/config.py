"""Application settings, read from environment variables (12-factor)."""
from functools import lru_cache

from pydantic import Field, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "vtc-api"
    log_level: str = "INFO"
    # OpenAPI docs (/docs, /openapi.json). Off by default in production.
    enable_docs: bool = False

    # --- Database -----------------------------------------------------------
    # e.g. postgresql+psycopg://app:password@10.128.0.2:5432/app
    database_url: str = Field(..., description="SQLAlchemy URL of the PostgreSQL database")
    db_pool_size: PositiveInt = 5
    db_max_overflow: int = 5
    db_pool_timeout_seconds: PositiveInt = 10

    # --- Firebase Authentication ---------------------------------------------
    # Firebase authenticates only. Authorization lives in PostgreSQL.
    firebase_project_id: str | None = None
    # Checking revocation costs one extra call to Google per request, but rejects
    # tokens of disabled / signed-out users immediately instead of within the hour.
    firebase_check_revoked: bool = True

    # Role given to every new user on first sign-in. Must exist in the `roles` table.
    default_role: str = "client-vtc-classique"

    # --- Driver GPS -------------------------------------------------------------
    # If set, locations are published to this Pub/Sub topic and written to the
    # database by the push subscription. If empty, they are written directly.
    gcp_project_id: str | None = None
    locations_topic: str | None = None
    pubsub_publish_timeout_seconds: PositiveInt = 10

    # Pub/Sub push authentication (OIDC token sent by the subscription)
    pubsub_verify_oidc: bool = True
    pubsub_audience: str | None = None
    pubsub_service_account: str | None = None

    location_max_batch: PositiveInt = 100
    location_max_age_seconds: PositiveInt = 24 * 3600
    location_max_future_seconds: PositiveInt = 300
    nearby_max_radius_m: PositiveInt = 20_000
    nearby_max_results: PositiveInt = 50
    nearby_freshness_seconds: PositiveInt = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()
