"""Permission codes referenced by the code.

The catalogue itself lives in PostgreSQL (seeded by migration 0003). Roles and their
permissions can be changed at runtime through the admin API without redeploying; only
permissions that the code checks need a constant here.
"""
from enum import StrEnum


class Perm(StrEnum):
    PROFILE_READ = "profile:read"
    LOCATION_WRITE = "location:write"            # a driver sends its own GPS positions
    LOCATION_READ_NEARBY = "location:read:nearby"  # see available drivers around a point
    LOCATION_READ = "location:read"              # read any driver's history
    USERS_READ = "users:read"
    RBAC_MANAGE = "rbac:manage"                  # manage roles, permissions and assignments


ADMIN_ROLE = "admin"
