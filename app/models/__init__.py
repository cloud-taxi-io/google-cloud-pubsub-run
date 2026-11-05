"""Import every model so `Base.metadata` is complete (used by Alembic)."""
from app.models.rbac import Permission, Role, User, UserRole, role_permissions

__all__ = ["Permission", "Role", "User", "UserRole", "role_permissions"]

# Tables managed with raw SQL (TimescaleDB hypertable / PostGIS geography), not mapped
# with the ORM. Alembic autogenerate must ignore them.
UNMAPPED_TABLES = frozenset({"driver_locations", "driver_last_locations"})
