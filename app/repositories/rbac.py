"""Data access for users, roles and permissions. No business rules here."""
from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.rbac import Permission, Role, User, UserRole, role_permissions


class RbacRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- users -------------------------------------------------------------
    def get_user(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def get_user_by_firebase_uid(self, firebase_uid: str) -> User | None:
        return self.db.scalar(select(User).where(User.firebase_uid == firebase_uid))

    def insert_user_if_absent(
        self, firebase_uid: str, email: str | None, phone_number: str | None, display_name: str | None
    ) -> bool:
        """Insert the user; return False if another request created it first (race-safe)."""
        stmt = (
            pg_insert(User)
            .values(
                id=uuid.uuid4(),
                firebase_uid=firebase_uid,
                email=email,
                phone_number=phone_number,
                display_name=display_name,
            )
            .on_conflict_do_nothing(index_elements=[User.firebase_uid])
            .returning(User.id)
        )
        return self.db.execute(stmt).first() is not None

    def list_users(self, limit: int, offset: int, firebase_uid: str | None = None) -> list[User]:
        stmt = select(User).order_by(User.created_at).limit(limit).offset(offset)
        if firebase_uid:
            stmt = stmt.where(User.firebase_uid == firebase_uid)
        return list(self.db.scalars(stmt))

    # --- permissions of a user (single query, used on every request) ----------
    def get_role_names(self, user_id: uuid.UUID) -> list[str]:
        stmt = (
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.name)
        )
        return list(self.db.scalars(stmt))

    def get_permission_codes(self, user_id: uuid.UUID) -> set[str]:
        stmt = (
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == role_permissions.c.role_id)
            .where(UserRole.user_id == user_id)
            .distinct()
        )
        return set(self.db.scalars(stmt))

    # --- roles ---------------------------------------------------------------
    def get_role(self, name: str) -> Role | None:
        return self.db.scalar(select(Role).where(Role.name == name))

    def list_roles(self) -> list[Role]:
        return list(self.db.scalars(select(Role).order_by(Role.name)))

    def add_role(self, role: Role) -> Role:
        self.db.add(role)
        self.db.flush()
        return role

    def delete_role(self, role: Role) -> None:
        self.db.delete(role)

    def count_users_with_role(self, role_id: int) -> int:
        return self.db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == role_id)) or 0

    def count_active_users_with_role(self, role_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(UserRole)
            .join(User, User.id == UserRole.user_id)
            .where(UserRole.role_id == role_id, User.is_active.is_(True))
        )
        return self.db.scalar(stmt) or 0

    # --- permissions -----------------------------------------------------------
    def get_permission(self, code: str) -> Permission | None:
        return self.db.scalar(select(Permission).where(Permission.code == code))

    def get_permissions(self, codes: list[str]) -> list[Permission]:
        if not codes:
            return []
        return list(self.db.scalars(select(Permission).where(Permission.code.in_(codes))))

    def list_permissions(self) -> list[Permission]:
        return list(self.db.scalars(select(Permission).order_by(Permission.code)))

    def add_permission(self, permission: Permission) -> Permission:
        self.db.add(permission)
        self.db.flush()
        return permission

    # --- assignments -------------------------------------------------------------
    def user_has_role(self, user_id: uuid.UUID, role_id: int) -> bool:
        stmt = select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
        return self.db.scalar(stmt) is not None

    def assign_role(self, user_id: uuid.UUID, role_id: int, assigned_by: uuid.UUID | None) -> bool:
        stmt = (
            pg_insert(UserRole)
            .values(user_id=user_id, role_id=role_id, assigned_by=assigned_by)
            .on_conflict_do_nothing()
            .returning(UserRole.user_id)
        )
        return self.db.execute(stmt).first() is not None

    def revoke_role(self, user_id: uuid.UUID, role_id: int) -> bool:
        stmt = delete(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
        return (self.db.execute(stmt).rowcount or 0) > 0
