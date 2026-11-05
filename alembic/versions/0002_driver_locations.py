"""Driver GPS: TimescaleDB hypertable (history) + PostGIS last-position table

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# How long the GPS history is kept (TimescaleDB drops whole chunks, cheaply).
RETENTION = "90 days"


def upgrade() -> None:
    # Already enabled on the VM by the startup script; IF NOT EXISTS keeps this idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # Full history, one row per GPS fix. The primary key makes Pub/Sub redeliveries idempotent.
    op.execute(
        """
        CREATE TABLE driver_locations (
            recorded_at  timestamptz NOT NULL,
            driver_id    uuid        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            geom         geography(Point, 4326) NOT NULL,
            speed_mps    real,
            heading_deg  real,
            accuracy_m   real,
            received_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_driver_locations PRIMARY KEY (driver_id, recorded_at)
        )
        """
    )
    op.execute(
        "SELECT create_hypertable('driver_locations', 'recorded_at', chunk_time_interval => INTERVAL '1 day')"
    )
    op.execute(f"SELECT add_retention_policy('driver_locations', INTERVAL '{RETENTION}')")

    # Latest position per driver: small table, fast "drivers near me" queries.
    op.execute(
        """
        CREATE TABLE driver_last_locations (
            driver_id    uuid        PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
            recorded_at  timestamptz NOT NULL,
            geom         geography(Point, 4326) NOT NULL,
            speed_mps    real,
            heading_deg  real,
            accuracy_m   real,
            updated_at   timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_driver_last_locations_geom ON driver_last_locations USING GIST (geom)")
    op.execute("CREATE INDEX ix_driver_last_locations_recorded_at ON driver_last_locations (recorded_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS driver_last_locations")
    op.execute("DROP TABLE IF EXISTS driver_locations")
