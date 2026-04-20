"""Tests for the local demo web UI."""

from io import BytesIO

from traffic_system import IncidentType
from traffic_system.webapp import application, reset_demo_system


def call_app(method: str = "GET", body: str = "", path: str = "/"):
    captured = {}
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(body.encode("utf-8"))),
        "wsgi.input": BytesIO(body.encode("utf-8")),
    }

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    chunks = application(environ, start_response)
    content = b"".join(chunks).decode("utf-8")
    return captured["status"], dict(captured["headers"]), content


def test_get_dashboard_renders_successfully():
    reset_demo_system()
    status, headers, content = call_app()
    assert status == "200 OK"
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert "Duster Local Demo" in content


def test_report_incident_via_post_updates_dashboard():
    reset_demo_system()
    status, _, content = call_app(
        method="POST",
        body="action=report_incident&route_id=R1&incident_type=ACCIDENT",
    )
    assert status == "200 OK"
    assert "Incident" in content
    assert "ACCIDENT" in content


def test_reset_demo_clears_new_incidents():
    reset_demo_system()
    call_app(
        method="POST",
        body=(
            f"action=report_incident&route_id=R2&incident_type={IncidentType.TRAFFIC_JAM.name}"
        ),
    )
    _, _, reset_content = call_app(method="POST", body="action=reset_demo")
    assert "Demo system reset" in reset_content
    assert "No active incidents." in reset_content


def test_unknown_path_returns_404():
    reset_demo_system()
    status, headers, content = call_app(path="/missing")
    assert status == "404 Not Found"
    assert headers["Content-Type"] == "text/plain; charset=utf-8"
    assert content == "Not Found"