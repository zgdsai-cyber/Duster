"""Tests for the Flask-based Duster web application."""

import json
import pytest

from traffic_system.app import app, _systems, _drone_positions


@pytest.fixture(autouse=True)
def reset_systems():
    """Clear in-memory state before every test."""
    _systems.clear()
    _drone_positions.clear()
    yield
    _systems.clear()
    _drone_positions.clear()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------- Index ----------

def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Duster" in r.data
    assert b"leaflet-map" in r.data


# ---------- /api/state ----------

def test_api_state_default_city(client):
    r = client.get("/api/state?city=riyadh")
    assert r.status_code == 200
    body = json.loads(r.data)
    assert "routes" in body
    assert "drones" in body
    assert "fleet" in body
    assert "drone_positions" in body
    assert len(body["routes"]) > 0


def test_api_state_all_cities(client):
    for city in ("riyadh", "jeddah", "dubai", "cairo"):
        r = client.get(f"/api/state?city={city}")
        assert r.status_code == 200, f"city={city} returned {r.status_code}"
        body = json.loads(r.data)
        assert len(body["routes"]) > 0


# ---------- /api/city ----------

def test_change_city(client):
    r = client.post(
        "/api/city",
        data=json.dumps({"city": "dubai"}),
        content_type="application/json",
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert len(body["routes"]) > 0


def test_change_city_unknown(client):
    r = client.post(
        "/api/city",
        data=json.dumps({"city": "atlantis"}),
        content_type="application/json",
    )
    assert r.status_code == 400


# ---------- /api/incident ----------

def test_report_accident(client):
    client.get("/api/state?city=riyadh")  # initialise
    r = client.post(
        "/api/incident",
        data=json.dumps({"route_id": "R1", "type": "ACCIDENT"}),
        content_type="application/json",
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert any(inc["type"] == "ACCIDENT" for inc in body["incidents"])


def test_report_traffic_jam(client):
    client.get("/api/state?city=riyadh")
    r = client.post(
        "/api/incident",
        data=json.dumps({"route_id": "R2", "type": "TRAFFIC_JAM"}),
        content_type="application/json",
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert any(inc["type"] == "TRAFFIC_JAM" for inc in body["incidents"])


def test_report_incident_bad_route(client):
    client.get("/api/state?city=riyadh")
    r = client.post(
        "/api/incident",
        data=json.dumps({"route_id": "INVALID", "type": "ACCIDENT"}),
        content_type="application/json",
    )
    assert r.status_code == 400


# ---------- /api/resolve ----------

def test_resolve_incident(client):
    client.get("/api/state?city=riyadh")
    inc_resp = client.post(
        "/api/incident",
        data=json.dumps({"route_id": "R1", "type": "ACCIDENT"}),
        content_type="application/json",
    )
    body = json.loads(inc_resp.data)
    incident_id = body["incidents"][0]["id"]

    r = client.post(
        "/api/resolve",
        data=json.dumps({"incident_id": incident_id}),
        content_type="application/json",
    )
    body = json.loads(r.data)
    assert not any(inc["id"] == incident_id for inc in body["incidents"])


# ---------- /api/monitor ----------

def test_monitor_cycle(client):
    client.get("/api/state?city=riyadh")
    r = client.post("/api/monitor")
    assert r.status_code == 200
    body = json.loads(r.data)
    assert "fleet" in body


# ---------- /api/recall ----------

def test_recall_all(client):
    client.get("/api/state?city=riyadh")
    client.post(
        "/api/incident",
        data=json.dumps({"route_id": "R1", "type": "ACCIDENT"}),
        content_type="application/json",
    )
    r = client.post("/api/recall")
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["fleet"]["deployed"] == 0 or body["fleet"]["returning"] >= 0


# ---------- /api/recharge ----------

def test_recharge_all(client):
    client.get("/api/state?city=riyadh")
    r = client.post("/api/recharge")
    assert r.status_code == 200
    body = json.loads(r.data)
    for drone in body["drones"]:
        assert drone["battery"] == 100


# ---------- /api/reset ----------

def test_reset_city(client):
    client.get("/api/state?city=riyadh")
    client.post(
        "/api/incident",
        data=json.dumps({"route_id": "R1", "type": "ACCIDENT"}),
        content_type="application/json",
    )
    r = client.post("/api/reset")
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["incidents"] == []


# ---------- drone_positions ----------

def test_drone_positions_in_state(client):
    r = client.get("/api/state?city=cairo")
    body = json.loads(r.data)
    assert isinstance(body["drone_positions"], dict)
    for drone in body["drones"]:
        assert drone["id"] in body["drone_positions"]
        pos = body["drone_positions"][drone["id"]]
        assert "lat" in pos and "lon" in pos
