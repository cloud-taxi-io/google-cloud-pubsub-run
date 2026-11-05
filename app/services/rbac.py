"""RBAC business rules. PostgreSQL is the single source of truth: no Firebase custom claims."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.permissions import ADMIN_ROLE
from app.core.security import FirebaseIdentity
from app.models.rbac import Permission, Role, User
from app.repositories.rbac import RbacRepository
from app.services.errors import ConflictError, ForbiddenOperationError, NotFoundError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller, with roles and permissions loaded from PostgreSQL."""

    user_id: uuid.UUID
    firebase_uid: str
    roles: frozenset[str]
    permissions: frozenset[str]

    def has_all(self, *codes: str) -> bool:
        return set(codes) <= self.permissions


class RbacService:
    def __init__(self, db: Session, default_role: str) -> None:
        self.db = db
        self.repo = RbacRepository(db)
        self.default_role = default_role

    # --- authentication -> principal ----------------------------------------------
    def resolve_principal(self, identity: FirebaseIdentity) -> tuple[User, Principal]:
        user = self._get_or_create_user(identity)
        principal = Principal(
            user_id=user.id,
            firebase_uid=user.firebase_uid,
            roles=frozenset(self.repo.get_role_names(user.id)),
            permissions=frozenset(self.repo.get_permission_codes(user.id)),
        )
        return user, principal

    def _get_or_create_user(self, identity: FirebaseIdentity) -> User:
        user = self.repo.get_user_by_firebase_uid(identity.uid)
        if user is None:
            created = self.repo.insert_user_if_absent(
                firebase_uid=identity.uid,
                email=identity.email if identity.email_verified else None,
                phone_number=identity.phone_number,
                display_name=identity.name,
            )
            user = self.repo.get_user_by_firebase_uid(identity.uid)
            if user is None:  # pragma: no cover - would mean the insert silently failed
                raise RuntimeError("user could not be created")
            if created:
                role = self.repo.get_role(self.default_role)
                if role is None:
                    raise RuntimeError(f"default role {self.default_role!r} is missing from the database")
                self.repo.assign_role(user.id, role.id, assigned_by=None)
                logger.info("user created", extra={"user_id": str(user.id), "role": role.name})
            self.db.commit()
            return user

        # Keep contact data in sync with Firebase (phone / verified email can change).
        new_phone = identity.phone_number or user.phone_number
        new_email = identity.email if identity.email_verified else user.email
        if (new_phone, new_email) != (user.phone_number, user.email):
            user.phone_number, user.email = new_phone, new_email
            self.db.commit()
        return user

    # --- users -----------------------------------------------------------------------
    def get_user(self, user_id: uuid.UUID) -> User:
        user = self.repo.get_user(user_id)
        if user is None:
            raise NotFoundError("user not found")
        return user

    def list_users(self, limit: int, offset: int, firebase_uid: str | None) -> list[User]:
        return self.repo.list_users(limit, offset, firebase_uid)

    def update_user(
        self, actor: Principal, user_id: uuid.UUID, is_active: bool | None, display_name: str | None
    ) -> User:
        user = self.get_user(user_id)
        if is_active is False and user.is_active:
            if user.id == actor.user_id:
                raise ForbiddenOperationError("you cannot deactivate yourself")
            self._ensure_not_last_admin(user, "deactivate")
        if is_active is not None:
            user.is_active = is_active
        if display_name is not None:
            user.display_name = display_name
        self.db.commit()
        self.db.refresh(user)
        logger.info(
            "user updated",
            extra={"actor": str(actor.user_id), "user_id": str(user.id), "is_active": user.is_active},
        )
        return user

    # --- roles -----------------------------------------------------------------------
    def list_roles(self) -> list[Role]:
        return self.repo.list_roles()

    def get_role(self, name: str) -> Role:
        role = self.repo.get_role(name)
        if role is None:
            raise NotFoundError(f"role {name!r} not found")
        return role

    def create_role(self, actor: Principal, name: str, description: str | None, permission_codes: list[str]) -> Role:
        if self.repo.get_role(name) is not None:
            raise ConflictError(f"role {name!r} already exists")
        permissions = self._get_permissions_or_fail(permission_codes)
        role = self.repo.add_role(Role(name=name, description=description, is_system=False))
        role.permissions.extend(permissions)
        self.db.commit()
        self.db.refresh(role)
        logger.info("role created", extra={"actor": str(actor.user_id), "role": name, "permissions": permission_codes})
        return role

    def delete_role(self, actor: Principal, name: str) -> None:
        role = self.get_role(name)
        if role.is_system:
            raise ForbiddenOperationError(f"system role {name!r} cannot be deleted")
        if self.repo.count_users_with_role(role.id):
            raise ConflictError(f"role {name!r} is still assigned to users")
        self.repo.delete_role(role)
        self.db.commit()
        logger.info("role deleted", extra={"actor": str(actor.user_id), "role": name})

    def grant_permission(self, actor: Principal, role_name: str, code: str) -> Role:
        role = self.get_role(role_name)
        permission = self._get_permission_or_fail(code)
        if permission not in role.permissions:
            role.permissions.append(permission)
            self.db.commit()
            logger.info("permission granted", extra={"actor": str(actor.user_id), "role": role_name, "permission": code})
        self.db.refresh(role)
        return role

    def revoke_permission(self, actor: Principal, role_name: str, code: str) -> Role:
        role = self.get_role(role_name)
        permission = self._get_permission_or_fail(code)
        if role.name == ADMIN_ROLE:
            raise ForbiddenOperationError("permissions of the admin role cannot be removed")
        if permission in role.permissions:
            role.permissions.remove(permission)
            self.db.commit()
            logger.info("permission revoked", extra={"actor": str(actor.user_id), "role": role_name, "permission": code})
        self.db.refresh(role)
        return role

    # --- permissions -------------------------------------------------------------------
    def list_permissions(self) -> list[Permission]:
        return self.repo.list_permissions()

    def create_permission(self, actor: Principal, code: str, description: str | None) -> Permission:
        if self.repo.get_permission(code) is not None:
            raise ConflictError(f"permission {code!r} already exists")
        permission = self.repo.add_permission(Permission(code=code, description=description))
        # The admin role always holds every permission.
        admin = self.repo.get_role(ADMIN_ROLE)
        if admin is not None:
            admin.permissions.append(permission)
        self.db.commit()
        logger.info("permission created", extra={"actor": str(actor.user_id), "permission": code})
        return permission

    # --- user <-> role -----------------------------------------------------------------
    def assign_role(self, actor: Principal, user_id: uuid.UUID, role_name: str) -> User:
        user = self.get_user(user_id)
        role = self.get_role(role_name)
        if self.repo.assign_role(user.id, role.id, assigned_by=actor.user_id):
            self.db.commit()
            logger.info(
                "role assigned", extra={"actor": str(actor.user_id), "user_id": str(user.id), "role": role_name}
            )
        self.db.refresh(user)
        return user

    def revoke_role(self, actor: Principal, user_id: uuid.UUID, role_name: str) -> User:
        user = self.get_user(user_id)
        role = self.get_role(role_name)
        if not self.repo.user_has_role(user.id, role.id):
            raise NotFoundError(f"user does not have role {role_name!r}")
        if role.name == ADMIN_ROLE:
            self._ensure_not_last_admin(user, "remove the admin role from")
        self.repo.revoke_role(user.id, role.id)
        self.db.commit()
        self.db.refresh(user)
        logger.info("role revoked", extra={"actor": str(actor.user_id), "user_id": str(user.id), "role": role_name})
        return user

    # --- helpers --------------------------------------------------------------------------
    def _ensure_not_last_admin(self, user: User, action: str) -> None:
        admin = self.repo.get_role(ADMIN_ROLE)
        if admin is None or not self.repo.user_has_role(user.id, admin.id):
            return
        if self.repo.count_active_users_with_role(admin.id) <= 1:
            raise ForbiddenOperationError(f"cannot {action} the last active admin")

    def _get_permission_or_fail(self, code: str) -> Permission:
        permission = self.repo.get_permission(code)
        if permission is None:
            raise NotFoundError(f"permission {code!r} not found")
        return permission

    def _get_permissions_or_fail(self, codes: list[str]) -> list[Permission]:
        wanted = set(codes)
        found = self.repo.get_permissions(sorted(wanted))
        missing = wanted - {p.code for p in found}
        if missing:
            raise NotFoundError(f"unknown permissions: {sorted(missing)}")
        return found
