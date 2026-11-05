from fastapi.testclient import TestClient

from tests.conftest import auth, user_id


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_missing_or_invalid_token_is_401(client: TestClient) -> None:
    assert client.get("/v1/me").status_code == 401
    r = client.get("/v1/me", headers={"Authorization": "Bearer not-a-valid-token"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_first_sign_in_creates_user_with_default_role(client: TestClient) -> None:
    r = client.get("/v1/me", headers=auth("u-client", "+213654818056"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["roles"] == ["client-vtc-classique"]
    assert body["permissions"] == ["location:read:nearby", "profile:read"]
    assert body["phone_number"] == "+213654818056"
    # Second call: same user, not duplicated
    assert client.get("/v1/me", headers=auth("u-client")).json()["id"] == body["id"]


def test_client_cannot_use_admin_api(client: TestClient) -> None:
    user_id(client, auth("u-client"))
    assert client.get("/v1/admin/roles", headers=auth("u-client")).status_code == 403
    assert client.get("/v1/admin/users", headers=auth("u-client")).status_code == 403


def test_multiple_roles_union_of_permissions(client: TestClient, admin: dict[str, str]) -> None:
    uid = user_id(client, auth("u-multi"))
    r = client.put(f"/v1/admin/users/{uid}/roles/taxi", headers=admin)
    assert r.status_code == 200
    assert sorted(x["name"] for x in r.json()["roles"]) == ["client-vtc-classique", "taxi"]
    me = client.get("/v1/me", headers=auth("u-multi")).json()
    assert me["roles"] == ["client-vtc-classique", "taxi"]
    assert set(me["permissions"]) == {"profile:read", "location:read:nearby", "location:write"}


def test_dynamic_roles_and_permissions_without_redeploy(client: TestClient, admin: dict[str, str]) -> None:
    uid = user_id(client, auth("u-vtc"))
    # New permission + new role, created at runtime
    r = client.post("/v1/admin/permissions", json={"code": "ride:accept"}, headers=admin)
    assert r.status_code == 201
    r = client.post(
        "/v1/admin/roles",
        json={"name": "chauffeur-vtc", "description": "VTC driver", "permissions": ["location:write", "ride:accept"]},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    assert {p["code"] for p in r.json()["permissions"]} == {"location:write", "ride:accept"}

    # The admin role automatically holds the new permission
    roles = {x["name"]: x for x in client.get("/v1/admin/roles", headers=admin).json()}
    assert "ride:accept" in {p["code"] for p in roles["admin"]["permissions"]}

    point = {"points": [{"recorded_at": _now(), "latitude": 36.75, "longitude": 3.06}]}
    assert client.post("/v1/drivers/me/locations", json=point, headers=auth("u-vtc")).status_code == 403
    client.put(f"/v1/admin/users/{uid}/roles/chauffeur-vtc", headers=admin)
    assert client.post("/v1/drivers/me/locations", json=point, headers=auth("u-vtc")).status_code == 202

    # Removing the permission from the role takes effect on the next request
    r = client.delete("/v1/admin/roles/chauffeur-vtc/permissions/location:write", headers=admin)
    assert r.status_code == 200
    assert client.post("/v1/drivers/me/locations", json=point, headers=auth("u-vtc")).status_code == 403


def test_role_rules(client: TestClient, admin: dict[str, str]) -> None:
    assert client.delete("/v1/admin/roles/taxi", headers=admin).status_code == 403  # system role
    assert client.post("/v1/admin/roles", json={"name": "taxi"}, headers=admin).status_code == 409
    r = client.post("/v1/admin/roles", json={"name": "x-role", "permissions": ["nope:nope"]}, headers=admin)
    assert r.status_code == 404
    assert client.post("/v1/admin/roles", json={"name": "Bad Name!"}, headers=admin).status_code == 422

    uid = user_id(client, auth("u-tmp"))
    client.post("/v1/admin/roles", json={"name": "temp-role"}, headers=admin)
    client.put(f"/v1/admin/users/{uid}/roles/temp-role", headers=admin)
    assert client.delete("/v1/admin/roles/temp-role", headers=admin).status_code == 409  # still assigned
    client.delete(f"/v1/admin/users/{uid}/roles/temp-role", headers=admin)
    assert client.delete("/v1/admin/roles/temp-role", headers=admin).status_code == 204
    assert client.delete("/v1/admin/roles/admin/permissions/rbac:manage", headers=admin).status_code == 403


def test_last_admin_is_protected(client: TestClient, admin: dict[str, str]) -> None:
    me = user_id(client, admin)
    assert client.delete(f"/v1/admin/users/{me}/roles/admin", headers=admin).status_code == 403
    assert client.patch(f"/v1/admin/users/{me}", json={"is_active": False}, headers=admin).status_code == 403

    other = user_id(client, auth("u-admin2"))
    client.put(f"/v1/admin/users/{other}/roles/admin", headers=admin)
    assert client.delete(f"/v1/admin/users/{me}/roles/admin", headers=admin).status_code == 200


def test_disabled_user_is_rejected(client: TestClient, admin: dict[str, str]) -> None:
    uid = user_id(client, auth("u-bad"))
    r = client.patch(f"/v1/admin/users/{uid}", json={"is_active": False}, headers=admin)
    assert r.status_code == 200 and r.json()["is_active"] is False
    r = client.get("/v1/me", headers=auth("u-bad"))
    assert r.status_code == 403 and r.json()["detail"] == "account disabled"


def test_admin_user_lookup(client: TestClient, admin: dict[str, str]) -> None:
    user_id(client, auth("u-look"))
    r = client.get("/v1/admin/users", params={"firebase_uid": "u-look"}, headers=admin)
    assert r.status_code == 200 and [u["firebase_uid"] for u in r.json()] == ["u-look"]
    assert client.get("/v1/admin/users/00000000-0000-0000-0000-000000000000", headers=admin).status_code == 404


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
