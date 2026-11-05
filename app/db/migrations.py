"""Shared Alembic helpers (used by alembic/env.py and the tests)."""
from typing import Any


def include_object(_obj: Any, _name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    # Never let autogenerate drop tables we do not map with the ORM:
    # TimescaleDB hypertables, PostGIS tables (spatial_ref_sys), etc.
    if type_ == "table" and reflected and compare_to is None:
        return False
    return True
