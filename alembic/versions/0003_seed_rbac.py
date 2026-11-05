"""Seed system roles and permissions

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05

Values are written here on purpose (not imported from the app): a migration must keep
doing the same thing even if the code changes later. Later changes to roles and
permissions go through the admin API, without redeploying.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = {
    "profile:read": "Read one's own profile",
    "location:write": "Send one's own GPS positions (drivers)",
    "location:read:nearby": "See available drivers around a point",
    "location:read": "Read the GPS history of any driver",
    "users:read": "List and read users",
    "rbac:manage": "Manage roles, permissions and role assignments",
}

ROLES = {
    "admin": ("Administrator: every permission", sorted(PERMISSIONS)),
    "taxi": ("Driver (taxi): sends GPS positions", ["profile:read", "location:write"]),
    "client-vtc-classique": (
        "Classic VTC customer: default role of new users",
        ["profile:read", "location:read:nearby"],
    ),
}


def upgrade() -> None:
    conn = op.get_bind()
    for code, description in PERMISSIONS.items():
        conn.execute(
            sa.text(
                "INSERT INTO permissions (code, description) VALUES (:code, :description) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "description": description},
        )
    for name, (description, codes) in ROLES.items():
        conn.execute(
            sa.text(
                "INSERT INTO roles (name, description, is_system) VALUES (:name, :description, true) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name, "description": description},
        )
        for code in codes:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (role_id, permission_id)
                    SELECT r.id, p.id FROM roles r, permissions p WHERE r.name = :name AND p.code = :code
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"name": name, "code": code},
            )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM roles WHERE name = ANY(:names)"), {"names": list(ROLES)})
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": list(PERMISSIONS)})
