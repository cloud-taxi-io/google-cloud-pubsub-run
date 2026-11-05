import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.conftest import auth, user_id

ALGIERS = (36.7538, 3.0588)


def _ts(seconds_ago: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()


def _driver(client: TestClient, admin: dict[str, str], uid: str = "u-driver") -> str:
    driver = user_id(client, auth(uid))
    assert client.put(f"/v1/admin/users/{driver}/roles/taxi", headers=admin).status_code == 200
    return driver


def test_driver_sends_gps_and_client_sees_it_nearby(client: TestClient, admin: dict[str, str]) -> None:
    driver = _driver(client, admin)
    batch = {
        "points": [
            {"recorded_at": _ts(20), "latitude": 36.7530, "longitude": 3.0580, "speed_mps": 8.5, "heading_deg": 90},
            {"recorded_at": _ts(10), "latitude": ALGIERS[0], "longitude": ALGIERS[1], "accuracy_m": 5},
        ]
    }
    r = client.post("/v1/drivers/me/locations", json=batch, headers=auth("u-driver"))
    assert r.status_code == 202, r.text
    assert r.json() == {"accepted": 2, "mode": "stored"}

    user_id(client, auth("u-client"))
    r = client.get("/v1/drivers/nearby", params={"lat": 36.7540, "lon": 3.0590}, headers=auth("u-client"))
    assert r.status_code == 200, r.text
    [found] = r.json()
    assert found["driver_id"] == driver
    assert abs(found["latitude"] - ALGIERS[0]) < 1e-6  # latest point, not the older one
    assert found["distance_m"] < 100

    # Far away: nobody
    r = client.get("/v1/drivers/nearby", params={"lat": 48.85, "lon": 2.35}, headers=auth("u-client"))
    assert r.json() == []

    # History: admin only
    assert client.get(f"/v1/drivers/{driver}/locations", headers=auth("u-client")).status_code == 403
    r = client.get(f"/v1/drivers/{driver}/locations", headers=admin)
    assert r.status_code == 200 and len(r.json()) == 2


def test_only_drivers_can_send_gps(client: TestClient) -> None:
    user_id(client, auth("u-client"))
    batch = {"points": [{"recorded_at": _ts(), "latitude": 36.7, "longitude": 3.0}]}
    assert client.post("/v1/drivers/me/locations", json=batch, headers=auth("u-client")).status_code == 403
    assert client.post("/v1/drivers/me/locations", json=batch).status_code == 401


def test_driver_id_comes_from_token_not_from_payload(client: TestClient, admin: dict[str, str]) -> None:
    driver = _driver(client, admin)
    victim = str(uuid.uuid4())
    batch = {"driver_id": victim, "points": [{"recorded_at": _ts(), "latitude": 36.7, "longitude": 3.0}]}
    assert client.post("/v1/drivers/me/locations", json=batch, headers=auth("u-driver")).status_code == 202
    assert len(client.get(f"/v1/drivers/{driver}/locations", headers=admin).json()) == 1
    assert client.get(f"/v1/drivers/{victim}/locations", headers=admin).json() == []


def test_gps_validation(client: TestClient, admin: dict[str, str]) -> None:
    _driver(client, admin)
    h = auth("u-driver")
    bad = [
        {"points": []},
        {"points": [{"recorded_at": _ts(), "latitude": 91, "longitude": 3.0}]},
        {"points": [{"recorded_at": _ts(), "latitude": 36.7, "longitude": 181}]},
        {"points": [{"recorded_at": _ts(-3600), "latitude": 36.7, "longitude": 3.0}]},  # 1 h in the future
        {"points": [{"recorded_at": _ts(3 * 86400), "latitude": 36.7, "longitude": 3.0}]},  # too old
        {"points": [{"recorded_at": "2026-11-05T10:00:00", "latitude": 36.7, "longitude": 3.0}]},  # no timezone
        {"points": [{"recorded_at": _ts(), "latitude": 36.7, "longitude": 3.0, "speed_mps": -1}]},
        {"points": [{"recorded_at": _ts(i), "latitude": 36.7, "longitude": 3.0} for i in range(101)]},
    ]
    for body in bad:
        assert client.post("/v1/drivers/me/locations", json=body, headers=h).status_code == 422, body


def test_duplicates_are_ignored_and_last_position_never_goes_back(client: TestClient, admin: dict[str, str]) -> None:
    driver = _driver(client, admin)
    h = auth("u-driver")
    newest = {"recorded_at": _ts(5), "latitude": 36.80, "longitude": 3.10}
    older = {"recorded_at": _ts(60), "latitude": 36.70, "longitude": 3.00}
    client.post("/v1/drivers/me/locations", json={"points": [newest]}, headers=h)
    client.post("/v1/drivers/me/locations", json={"points": [newest]}, headers=h)  # duplicate
    client.post("/v1/drivers/me/locations", json={"points": [older]}, headers=h)  # late delivery
    assert len(client.get(f"/v1/drivers/{driver}/locations", headers=admin).json()) == 2

    user_id(client, auth("u-client"))
    [found] = client.get(
        "/v1/drivers/nearby", params={"lat": 36.80, "lon": 3.10, "radius_m": 50_000}, headers=auth("u-client")
    ).json()
    assert abs(found["latitude"] - 36.80) < 1e-6


def test_stale_and_disabled_drivers_are_not_nearby(client: TestClient, admin: dict[str, str]) -> None:
    driver = _driver(client, admin)
    client.post(
        "/v1/drivers/me/locations",
        json={"points": [{"recorded_at": _ts(600), "latitude": ALGIERS[0], "longitude": ALGIERS[1]}]},
        headers=auth("u-driver"),
    )
    user_id(client, auth("u-client"))
    params = {"lat": ALGIERS[0], "lon": ALGIERS[1]}
    assert client.get("/v1/drivers/nearby", params=params, headers=auth("u-client")).json() == []  # 10 min old

    client.post(
        "/v1/drivers/me/locations",
        json={"points": [{"recorded_at": _ts(), "latitude": ALGIERS[0], "longitude": ALGIERS[1]}]},
        headers=auth("u-driver"),
    )
    assert len(client.get("/v1/drivers/nearby", params=params, headers=auth("u-client")).json()) == 1
    client.patch(f"/v1/admin/users/{driver}", json={"is_active": False}, headers=admin)
    assert client.get("/v1/drivers/nearby", params=params, headers=auth("u-client")).json() == []


def _push(client: TestClient, payload: object, msg_type: str = "driver_location") -> int:
    data = base64.b64encode(json.dumps(payload).encode() if not isinstance(payload, bytes) else payload).decode()
    envelope = {"message": {"data": data, "attributes": {"type": msg_type}, "messageId": "1"}, "subscription": "s"}
    return client.post("/pubsub/push", json=envelope).status_code


def test_pubsub_push_stores_locations(client: TestClient, admin: dict[str, str]) -> None:
    driver = _driver(client, admin)
    msg = {"schema_version": 1, "driver_id": driver, "points": [{"recorded_at": _ts(), "latitude": 36.7, "longitude": 3.0}]}
    assert _push(client, msg) == 204
    assert len(client.get(f"/v1/drivers/{driver}/locations", headers=admin).json()) == 1


def test_pubsub_poison_messages_are_acked(client: TestClient) -> None:
    unknown = {"driver_id": str(uuid.uuid4()), "points": [{"recorded_at": _ts(), "latitude": 36.7, "longitude": 3.0}]}
    assert _push(client, unknown) == 204  # unknown driver: FK violation, acked
    assert _push(client, {"driver_id": "x", "points": []}) == 204  # invalid payload
    assert _push(client, b"not json") == 204
    assert _push(client, {"hello": "world"}, msg_type="other") == 204  # other message type
    assert client.post("/pubsub/push", json={"nope": 1}).status_code == 422  # not a Pub/Sub envelope


def test_queued_mode_publishes_with_driver_id_from_token(client: TestClient, admin: dict[str, str]) -> None:
    from app.api.deps import get_location_publisher
    from app.main import app

    sent = []

    class FakePublisher:
        def publish(self, message):  # noqa: ANN001, ANN202
            sent.append(message)

    driver = _driver(client, admin)
    app.dependency_overrides[get_location_publisher] = FakePublisher
    try:
        batch = {"points": [{"recorded_at": _ts(), "latitude": 36.7, "longitude": 3.0}]}
        r = client.post("/v1/drivers/me/locations", json=batch, headers=auth("u-driver"))
    finally:
        del app.dependency_overrides[get_location_publisher]
    assert r.status_code == 202 and r.json() == {"accepted": 1, "mode": "queued"}
    assert [str(m.driver_id) for m in sent] == [driver]
    # Nothing written directly: the push subscription does it
    assert client.get(f"/v1/drivers/{driver}/locations", headers=admin).json() == []
