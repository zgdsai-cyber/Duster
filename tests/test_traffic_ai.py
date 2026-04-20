"""Tests for traffic_ai module (mocked external calls)."""

import json
from unittest.mock import MagicMock, patch

import pytest

import traffic_system.traffic_ai as ai
from traffic_system.app import app, _systems, _drone_positions


@pytest.fixture(autouse=True)
def reset():
    _systems.clear()
    _drone_positions.clear()
    ai._config["groq_api_key"] = ""
    ai._config["tomtom_api_key"] = ""
    yield
    _systems.clear()
    _drone_positions.clear()


# ---- configure / is_configured ----

def test_configure_sets_keys():
    ai.configure("groq-key-123", "tomtom-key-456")
    assert ai.is_configured() is True


def test_not_configured_by_default():
    assert ai.is_configured() is False


# ---- fetch_route_traffic ----

def test_fetch_route_traffic_parses_response():
    fake_response = {
        "flowSegmentData": {
            "currentSpeed": 40,
            "freeFlowSpeed": 80,
            "confidence": 0.9,
            "roadClosure": False,
        }
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status.return_value = None

    with patch("traffic_system.traffic_ai.requests.get", return_value=mock_resp):
        result = ai.fetch_route_traffic(24.7, 46.7, "dummy-key")

    assert result["current_speed_kmh"] == 40
    assert result["free_flow_speed_kmh"] == 80
    assert result["congestion_score"] == 50  # (1 - 40/80) * 100
    assert result["road_closure"] is False


def test_fetch_route_traffic_road_closure():
    fake_response = {
        "flowSegmentData": {
            "currentSpeed": 0,
            "freeFlowSpeed": 100,
            "confidence": 1.0,
            "roadClosure": True,
        }
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status.return_value = None

    with patch("traffic_system.traffic_ai.requests.get", return_value=mock_resp):
        result = ai.fetch_route_traffic(24.7, 46.7, "dummy-key")

    assert result["congestion_score"] == 100
    assert result["road_closure"] is True


# ---- fetch_traffic_data ----

def test_fetch_traffic_data_handles_network_error():
    routes = [{"id": "R1", "name": "Test Road", "lat": 24.7, "lon": 46.7}]
    ai.configure("g", "t")
    with patch("traffic_system.traffic_ai.requests.get", side_effect=Exception("timeout")):
        results = ai.fetch_traffic_data(routes)
    assert len(results) == 1
    assert "error" in results[0]
    assert results[0]["route_id"] == "R1"


def test_fetch_traffic_data_skips_no_coords():
    routes = [{"id": "R1", "name": "No Coords"}]  # no lat/lon
    ai.configure("g", "t")
    results = ai.fetch_traffic_data(routes)
    assert results == []


# ---- analyze_with_ai ----

SAMPLE_DECISIONS = [
    {"route_id": "R1", "action": "deploy_accident", "reason": "إغلاق الطريق"},
    {"route_id": "R2", "action": "none", "reason": "حركة سلسة"},
]


def test_analyze_with_ai_returns_decisions():
    ai.configure("groq-key", "tomtom-key")
    fake_response = {
        "choices": [{"message": {"content": json.dumps(SAMPLE_DECISIONS)}}]
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status.return_value = None

    with patch("traffic_system.traffic_ai.requests.post", return_value=mock_resp):
        decisions, raw = ai.analyze_with_ai([], {"idle": 4, "deployed": 0, "returning": 0, "total": 4})

    assert len(decisions) == 2
    assert decisions[0]["action"] == "deploy_accident"


def test_analyze_with_ai_extracts_json_from_markdown():
    ai.configure("groq-key", "tomtom-key")
    markdown = "```json\n" + json.dumps(SAMPLE_DECISIONS) + "\n```"
    fake_response = {"choices": [{"message": {"content": markdown}}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status.return_value = None

    with patch("traffic_system.traffic_ai.requests.post", return_value=mock_resp):
        decisions, _ = ai.analyze_with_ai([], {"idle": 4, "deployed": 0, "returning": 0, "total": 4})

    assert len(decisions) == 2


def test_analyze_with_ai_raises_without_key():
    with pytest.raises(RuntimeError, match="Groq"):
        ai.analyze_with_ai([], {})


# ---- execute_decisions ----

def _make_system():
    from traffic_system import Drone, Route, TrafficMonitoringSystem
    system = TrafficMonitoringSystem()
    system.add_route(Route("R1", "Road 1", congestion_score=85))
    system.add_route(Route("R2", "Road 2", congestion_score=20))
    for i in range(3):
        system.add_drone(Drone(f"D{i}"))
    return system


def test_execute_accident_decision():
    system = _make_system()
    decisions = [{"route_id": "R1", "action": "deploy_accident", "reason": "حادث"}]
    results = ai.execute_decisions(decisions, system)
    assert results[0]["status"] == "deployed"
    assert "incident_id" in results[0]


def test_execute_jam_decision():
    system = _make_system()
    decisions = [{"route_id": "R1", "action": "deploy_jam", "reason": "ازدحام"}]
    results = ai.execute_decisions(decisions, system)
    assert results[0]["status"] == "deployed"


def test_execute_recall_resolves_incidents():
    system = _make_system()
    # First create an incident
    inc = system.report_incident("R1", __import__("traffic_system.models", fromlist=["IncidentType"]).IncidentType.ACCIDENT)
    assert inc.incident_id in system.active_incidents
    decisions = [{"route_id": "R1", "action": "recall", "reason": "حركة سلسة"}]
    ai.execute_decisions(decisions, system)
    assert inc.incident_id not in system.active_incidents


def test_execute_unknown_route():
    system = _make_system()
    decisions = [{"route_id": "FAKE", "action": "deploy_accident", "reason": "test"}]
    results = ai.execute_decisions(decisions, system)
    assert results[0]["status"] == "unknown_route"


# ---- Flask AI endpoints ----

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_ai_configure_endpoint(client):
    r = client.post(
        "/api/ai/configure",
        json={"groq_api_key": "gk", "tomtom_api_key": "tk"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["configured"] is True


def test_ai_configure_missing_keys(client):
    r = client.post("/api/ai/configure", json={"groq_api_key": ""})
    assert r.status_code == 400


def test_ai_status_endpoint(client):
    r = client.get("/api/ai/status")
    assert r.status_code == 200
    body = r.get_json()
    assert "configured" in body
    assert "last_result" in body


def test_ai_run_without_config(client):
    r = client.post("/api/ai/run")
    assert r.status_code == 400


def test_ai_run_with_mocked_apis(client):
    ai.configure("groq-key", "tomtom-key")
    snapshot = [{"route_id": "R1", "name": "R", "congestion_score": 85,
                 "current_speed_kmh": 20, "free_flow_speed_kmh": 80,
                 "road_closure": False, "confidence": 0.9}]
    decisions = [{"route_id": "R1", "action": "deploy_jam", "reason": "ازدحام"}]
    raw_ai = json.dumps(decisions)

    with patch("traffic_system.traffic_ai.fetch_traffic_data", return_value=snapshot), \
         patch("traffic_system.traffic_ai.analyze_with_ai", return_value=(decisions, raw_ai)):
        r = client.post("/api/ai/run")

    assert r.status_code == 200
    body = r.get_json()
    assert "ai_result" in body
    assert body["ai_result"]["decisions"][0]["action"] == "deploy_jam"
