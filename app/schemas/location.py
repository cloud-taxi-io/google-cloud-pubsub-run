from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from app.core.config import get_settings


class LocationPoint(BaseModel):
    """One GPS fix sent by the driver's phone."""

    recorded_at: AwareDatetime = Field(description="When the phone took the fix (ISO 8601 with timezone)")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    speed_mps: float | None = Field(default=None, ge=0, le=100)
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    accuracy_m: float | None = Field(default=None, ge=0, le=10_000)

    @field_validator("recorded_at")
    @classmethod
    def _not_too_old_or_in_the_future(cls, value: datetime) -> datetime:
        settings = get_settings()
        now = datetime.now(UTC)
        if value > now + timedelta(seconds=settings.location_max_future_seconds):
            raise ValueError("recorded_at is in the future")
        if value < now - timedelta(seconds=settings.location_max_age_seconds):
            raise ValueError("recorded_at is too old")
        return value.astimezone(UTC)


class LocationBatch(BaseModel):
    """Phones buffer fixes while offline and send them in batches."""

    points: list[LocationPoint] = Field(min_length=1)

    @field_validator("points")
    @classmethod
    def _max_batch(cls, value: list[LocationPoint]) -> list[LocationPoint]:
        limit = get_settings().location_max_batch
        if len(value) > limit:
            raise ValueError(f"at most {limit} points per batch")
        return value


class LocationAccepted(BaseModel):
    accepted: int
    mode: str = Field(description="'queued' (Pub/Sub) or 'stored' (written directly)")


class DriverLocationMessage(BaseModel):
    """Pub/Sub message body. `driver_id` is set by the API from the verified token, never by the phone."""

    schema_version: int = 1
    driver_id: uuid.UUID
    points: list[LocationPoint]


class NearbyDriver(BaseModel):
    driver_id: uuid.UUID
    latitude: float
    longitude: float
    distance_m: float
    heading_deg: float | None
    recorded_at: datetime


class LocationOut(BaseModel):
    recorded_at: datetime
    latitude: float
    longitude: float
    speed_mps: float | None
    heading_deg: float | None
    accuracy_m: float | None
