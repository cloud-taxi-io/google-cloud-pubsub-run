"""Data access for driver GPS positions (TimescaleDB hypertable + PostGIS)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.orm import Session

from app.schemas.location import LocationOut, LocationPoint, NearbyDriver

_INSERT_HISTORY = text(
    """
    INSERT INTO driver_locations (recorded_at, driver_id, geom, speed_mps, heading_deg, accuracy_m)
    VALUES (:recorded_at, :driver_id,
            ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
            :speed_mps, :heading_deg, :accuracy_m)
    ON CONFLICT (driver_id, recorded_at) DO NOTHING
    """
)

# Only move the "last position" forward in time (Pub/Sub may deliver out of order).
_UPSERT_LAST = text(
    """
    INSERT INTO driver_last_locations (driver_id, recorded_at, geom, speed_mps, heading_deg, accuracy_m)
    VALUES (:driver_id, :recorded_at,
            ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
            :speed_mps, :heading_deg, :accuracy_m)
    ON CONFLICT (driver_id) DO UPDATE
       SET recorded_at = EXCLUDED.recorded_at,
           geom        = EXCLUDED.geom,
           speed_mps   = EXCLUDED.speed_mps,
           heading_deg = EXCLUDED.heading_deg,
           accuracy_m  = EXCLUDED.accuracy_m,
           updated_at  = now()
     WHERE driver_last_locations.recorded_at < EXCLUDED.recorded_at
    """
)

_NEARBY = text(
    """
    SELECT l.driver_id,
           ST_Y(l.geom::geometry) AS latitude,
           ST_X(l.geom::geometry) AS longitude,
           ST_Distance(l.geom, c.center)  AS distance_m,
           l.heading_deg,
           l.recorded_at
      FROM driver_last_locations l
      JOIN users u ON u.id = l.driver_id AND u.is_active
     CROSS JOIN (SELECT ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography AS center) c
     WHERE l.recorded_at >= now() - make_interval(secs => :freshness_seconds)
       AND ST_DWithin(l.geom, c.center, :radius_m)
     ORDER BY distance_m
     LIMIT :limit
    """
)

_HISTORY = text(
    """
    SELECT recorded_at,
           ST_Y(geom::geometry) AS latitude,
           ST_X(geom::geometry) AS longitude,
           speed_mps, heading_deg, accuracy_m
      FROM driver_locations
     WHERE driver_id = :driver_id
       AND recorded_at >= :since
       AND recorded_at <  :until
     ORDER BY recorded_at DESC
     LIMIT :limit
    """
)


class LocationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save_points(self, driver_id: uuid.UUID, points: list[LocationPoint]) -> int:
        """Idempotent: re-delivered points (same driver + timestamp) are ignored."""
        rows = [{"driver_id": driver_id, **p.model_dump()} for p in points]
        result = cast(CursorResult[Any], self.db.execute(_INSERT_HISTORY, rows))
        latest = max(points, key=lambda p: p.recorded_at)
        self.db.execute(_UPSERT_LAST, {"driver_id": driver_id, **latest.model_dump()})
        return result.rowcount if result.rowcount >= 0 else len(rows)

    def nearby(
        self, *, latitude: float, longitude: float, radius_m: int, freshness_seconds: int, limit: int
    ) -> list[NearbyDriver]:
        rows = self.db.execute(
            _NEARBY,
            {
                "latitude": latitude,
                "longitude": longitude,
                "radius_m": radius_m,
                "freshness_seconds": freshness_seconds,
                "limit": limit,
            },
        ).mappings()
        return [NearbyDriver(**row) for row in rows]

    def history(self, driver_id: uuid.UUID, since: datetime, until: datetime, limit: int) -> list[LocationOut]:
        rows = self.db.execute(
            _HISTORY, {"driver_id": driver_id, "since": since, "until": until, "limit": limit}
        ).mappings()
        return [LocationOut(**row) for row in rows]
