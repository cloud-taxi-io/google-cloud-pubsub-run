"""Integration tests against a real PostgreSQL + PostGIS + TimescaleDB.

Start one with:
    docker run -d --name vtc-test-db -p 55432:5432 -e POSTGRES_PASSWORD=test timescale/timescaledb-ha:pg17
    export TEST_DATABASE_URL=postgresql+psycopg://postgres:test@localhost:55432/postgres

Only Firebase is faked (FakeVerifier); the database, migrations and SQL are real.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

_DB_URL = os.environ.get("TEST_DATABASE_URL")
if not _DB_URL:
    pytest.exit("TEST_DATABASE_URL is not set (see tests/conftest.py)", returncode=2)

os.environ["DATABASE_URL"] = _DB_URL
os.environ["PUBSUB_VERIFY_OIDC"] = "false"
os.environ.pop("LOCATIONS_TOPIC", None)
os.environ["FIREBASE_CHECK_REVOKED"] = "false"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.api.deps import get_token_verifier  # noqa: E402
from app.cli import grant_role  # noqa: E402
from app.core.security import FirebaseIdentity, InvalidTokenError  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.main import app  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeVerifier:
    """Token format: 'uid:<firebase_uid>' or 'uid:<firebase_uid>:<phone>'."""

    def verify(self, token: str) -> FirebaseIdentity:
        parts = token.split(":")
        if len(parts) < 2 or parts[0] != "uid":
            raise InvalidTokenError("bad fake token")
        return FirebaseIdentity(
            uid=parts[1],
            email=None,
            email_verified=False,
            phone_number=parts[2] if len(parts) > 2 else None,
            name=None,
            sign_in_provider="phone",
        )


def auth(uid: str, phone: str | None = None) -> dict[str, str]:
    token = f"uid:{uid}" + (f":{phone}" if phone else "")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> Iterator[None]:
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public"))
        conn.execute(text("DROP EXTENSION IF EXISTS timescaledb CASCADE"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    yield
    with get_engine().begin() as conn:
        conn.execute(text("TRUNCATE driver_locations, driver_last_locations, user_roles, users"))
        conn.execute(text("DELETE FROM roles WHERE NOT is_system"))
        conn.execute(
            text(
                "DELETE FROM permissions WHERE code NOT IN "
                "('profile:read','location:write','location:read:nearby','location:read','users:read','rbac:manage')"
            )
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    assert grant_role("admin-uid", "admin", create=True) == 0
    return auth("admin-uid")


def user_id(client: TestClient, headers: dict[str, str]) -> str:
    r = client.get("/v1/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]
