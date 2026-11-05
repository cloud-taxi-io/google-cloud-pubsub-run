from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

import app.models  # noqa: F401
from app.db.base import Base
from app.db.migrations import include_object
from app.db.session import get_engine


def test_models_match_migrations() -> None:
    """The ORM models and the Alembic migrations describe the same schema."""
    with get_engine().connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"include_object": include_object, "compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == []


def test_hypertable_and_seed() -> None:
    with get_engine().connect() as conn:
        hypertables = conn.execute(text("SELECT hypertable_name FROM timescaledb_information.hypertables")).scalars()
        assert "driver_locations" in set(hypertables)
        roles = set(conn.execute(text("SELECT name FROM roles WHERE is_system")).scalars())
        assert roles == {"admin", "taxi", "client-vtc-classique"}
