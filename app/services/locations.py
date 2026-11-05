"""Driver GPS ingestion: API -> (Pub/Sub) -> TimescaleDB/PostGIS."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.locations import LocationRepository
from app.schemas.location import DriverLocationMessage, LocationOut, LocationPoint, NearbyDriver

logger = logging.getLogger(__name__)

MESSAGE_TYPE = "driver_location"


class LocationPublisher(Protocol):
    def publish(self, message: DriverLocationMessage) -> None: ...


class PubSubLocationPublisher:
    def __init__(self, settings: Settings) -> None:
        from google.cloud import pubsub_v1  # imported lazily: optional at runtime

        if not settings.gcp_project_id or not settings.locations_topic:
            raise RuntimeError("GCP_PROJECT_ID and LOCATIONS_TOPIC are required to publish locations")
        self._client = pubsub_v1.PublisherClient()
        self._topic = self._client.topic_path(settings.gcp_project_id, settings.locations_topic)
        self._timeout = settings.pubsub_publish_timeout_seconds

    def publish(self, message: DriverLocationMessage) -> None:
        future = self._client.publish(
            self._topic,
            message.model_dump_json().encode("utf-8"),
            type=MESSAGE_TYPE,
            schema_version=str(message.schema_version),
            # Same driver -> same ordering key (only effective if ordering is enabled on the subscription)
            driver_id=str(message.driver_id),
        )
        future.result(timeout=self._timeout)  # raise if Pub/Sub did not accept the message


class LocationService:
    def __init__(self, db: Session, settings: Settings, publisher: LocationPublisher | None) -> None:
        self.repo = LocationRepository(db)
        self.db = db
        self.settings = settings
        self.publisher = publisher

    def ingest(self, driver_id: uuid.UUID, points: list[LocationPoint]) -> str:
        """Called by the API with the *authenticated* driver id. Returns 'queued' or 'stored'."""
        if self.publisher is not None:
            self.publisher.publish(DriverLocationMessage(driver_id=driver_id, points=points))
            return "queued"
        self.store(driver_id, points)
        return "stored"

    def store(self, driver_id: uuid.UUID, points: list[LocationPoint]) -> int:
        inserted = self.repo.save_points(driver_id, points)
        self.db.commit()
        return inserted

    def nearby(self, latitude: float, longitude: float, radius_m: int, limit: int) -> list[NearbyDriver]:
        return self.repo.nearby(
            latitude,
            longitude,
            radius_m=min(radius_m, self.settings.nearby_max_radius_m),
            freshness_seconds=self.settings.nearby_freshness_seconds,
            limit=min(limit, self.settings.nearby_max_results),
        )

    def history(self, driver_id: uuid.UUID, since: datetime, until: datetime, limit: int) -> list[LocationOut]:
        return self.repo.history(driver_id, since, until, limit)
