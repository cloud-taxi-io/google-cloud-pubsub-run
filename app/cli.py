"""Operator commands that need direct database access.

Bootstrap the first admin (the admin API itself requires an admin):

    python -m app.cli grant-role <firebase_uid> admin --create
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.db.session import get_session_factory
from app.models.rbac import Role, User, UserRole


def grant_role(firebase_uid: str, role_name: str, create: bool) -> int:
    with get_session_factory()() as db:
        role = db.scalar(select(Role).where(Role.name == role_name))
        if role is None:
            print(f"role {role_name!r} not found", file=sys.stderr)
            return 1
        user = db.scalar(select(User).where(User.firebase_uid == firebase_uid))
        if user is None:
            if not create:
                print("user not found (sign in once with the app, or pass --create)", file=sys.stderr)
                return 1
            user = User(firebase_uid=firebase_uid)
            db.add(user)
            db.flush()
        exists = db.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id))
        if exists is None:
            db.add(UserRole(user_id=user.id, role_id=role.id))
        db.commit()
        print(f"user {user.id} ({firebase_uid}) has role {role_name}")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    grant = sub.add_parser("grant-role", help="give a role to a user, identified by Firebase UID")
    grant.add_argument("firebase_uid")
    grant.add_argument("role")
    grant.add_argument("--create", action="store_true", help="create the user if it never signed in")
    args = parser.parse_args(argv)
    if args.command == "grant-role":
        return grant_role(args.firebase_uid, args.role, args.create)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
