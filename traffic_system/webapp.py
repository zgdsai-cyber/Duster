"""Local web UI for manually trying the traffic monitoring system."""

from html import escape
from io import BytesIO
from typing import Dict, Iterable, Tuple
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from traffic_system import Drone, IncidentType, Route, TrafficMonitoringSystem


def create_demo_system() -> TrafficMonitoringSystem:
    """Build a ready-to-try system with sample routes and drones."""
    system = TrafficMonitoringSystem()
    system.add_route(Route("R1", "Main Street", congestion_score=25))
    system.add_route(Route("R2", "Highway 5", congestion_score=85))
    system.add_route(Route("R3", "River Road", congestion_score=55))

    for index in range(1, 6):
        system.add_drone(Drone(f"D{index}"))

    return system


SYSTEM = create_demo_system()


def reset_demo_system() -> TrafficMonitoringSystem:
    """Reset the in-memory demo state."""
    global SYSTEM
    SYSTEM = create_demo_system()
    return SYSTEM


def _read_form_data(environ: dict) -> Dict[str, str]:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    raw_body = environ["wsgi.input"].read(length).decode("utf-8") if length else ""
    parsed = parse_qs(raw_body, keep_blank_values=True)
    return {key: values[0] for key, values in parsed.items()}


def _handle_action(data: Dict[str, str]) -> str:
    action = data.get("action", "")
    system = SYSTEM

    if action == "monitor":
        results = system.monitor()
        return f"Monitoring cycle completed for {len(results)} route(s)."

    if action == "reset_demo":
        reset_demo_system()
        return "Demo system reset to the default sample state."

    if action == "recall_all":
        system.fleet.recall_all(system.routes)
        return "All deployed drones were recalled to base."

    if action == "recharge_all":
        system.fleet.recharge_all()
        return "All drones were recharged and returned to idle status."

    if action == "report_incident":
        route_id = data.get("route_id", "")
        incident_name = data.get("incident_type", "ACCIDENT")
        incident_type = IncidentType[incident_name]
        incident = system.report_incident(route_id, incident_type)
        return f"Incident {incident.incident_id} created on route {route_id}."

    if action == "resolve_incident":
        incident_id = data.get("incident_id", "")
        resolved = system.resolve_incident(incident_id)
        if resolved:
            return f"Incident {incident_id} marked as resolved."
        return f"Incident {incident_id} was not found."

    return "No action was executed."


def _render_dashboard(message: str = "") -> str:
    system = SYSTEM
    report = system.status_report()
    routes = sorted(system.routes.values(), key=lambda route: route.route_id)
    incidents = sorted(system.active_incidents.values(), key=lambda item: item.route_id)
    drones = sorted(system.fleet.drones, key=lambda drone: drone.drone_id)
    fleet = report["fleet"]

    route_rows = "".join(
        f"""
        <tr>
          <td>{escape(route.route_id)}</td>
          <td>{escape(route.name)}</td>
          <td>{route.congestion_score}</td>
          <td>{escape(route.congestion_level().value)}</td>
          <td>{'Yes' if route.has_accident else 'No'}</td>
          <td>{escape(', '.join(route.assigned_drones) or '-')}</td>
          <td class=\"actions\">
            <form method=\"post\">
              <input type=\"hidden\" name=\"action\" value=\"report_incident\">
              <input type=\"hidden\" name=\"route_id\" value=\"{escape(route.route_id)}\">
              <input type=\"hidden\" name=\"incident_type\" value=\"ACCIDENT\">
              <button type=\"submit\">Accident</button>
            </form>
            <form method=\"post\">
              <input type=\"hidden\" name=\"action\" value=\"report_incident\">
              <input type=\"hidden\" name=\"route_id\" value=\"{escape(route.route_id)}\">
              <input type=\"hidden\" name=\"incident_type\" value=\"TRAFFIC_JAM\">
              <button type=\"submit\">Traffic Jam</button>
            </form>
          </td>
        </tr>
        """
        for route in routes
    )

    incident_rows = "".join(
        f"""
        <tr>
          <td>{escape(incident.incident_id)}</td>
          <td>{escape(incident.route_id)}</td>
          <td>{escape(incident.incident_type.name)}</td>
          <td>
            <form method=\"post\">
              <input type=\"hidden\" name=\"action\" value=\"resolve_incident\">
              <input type=\"hidden\" name=\"incident_id\" value=\"{escape(incident.incident_id)}\">
              <button type=\"submit\">Resolve</button>
            </form>
          </td>
        </tr>
        """
        for incident in incidents
    ) or '<tr><td colspan="4">No active incidents.</td></tr>'

    drone_rows = "".join(
        f"""
        <tr>
          <td>{escape(drone.drone_id)}</td>
          <td>{escape(drone.status.value)}</td>
          <td>{drone.battery_level}%</td>
          <td>{escape(drone.assigned_route_id or '-')}</td>
        </tr>
        """
        for drone in drones
    )

    banner = f"<div class=\"banner\">{escape(message)}</div>" if message else ""

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Duster Local Demo</title>
  <style>
    :root {{
      --bg: #f3efe5;
      --panel: rgba(255,255,255,0.78);
      --ink: #132a13;
      --muted: #4f6f52;
      --accent: #bc6c25;
      --accent-dark: #8d5524;
      --line: rgba(19,42,19,0.12);
      --ok: #3a7d44;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(188,108,37,0.28), transparent 28%),
        radial-gradient(circle at right, rgba(95,141,78,0.18), transparent 22%),
        linear-gradient(180deg, #f8f5ef 0%, var(--bg) 100%);
    }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 32px 20px 64px; }}
    .hero {{
      background: linear-gradient(135deg, rgba(19,42,19,0.96), rgba(79,111,82,0.92));
      color: #fefae0;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 50px rgba(19,42,19,0.18);
    }}
    .hero h1 {{ margin: 0 0 10px; font-size: 2.4rem; }}
    .hero p {{ margin: 0; max-width: 760px; line-height: 1.6; color: rgba(254,250,224,0.9); }}
    .banner {{
      margin: 20px 0 0;
      background: rgba(254,250,224,0.92);
      color: var(--accent-dark);
      border-left: 5px solid var(--accent);
      padding: 14px 16px;
      border-radius: 12px;
      font-weight: 700;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin: 22px 0;
    }}
    .metric, section {{
      background: var(--panel);
      backdrop-filter: blur(10px);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 12px 32px rgba(19,42,19,0.08);
    }}
    .metric {{ padding: 18px; }}
    .metric strong {{ display: block; color: var(--muted); font-size: 0.92rem; text-transform: uppercase; letter-spacing: 0.08em; }}
    .metric span {{ display: block; margin-top: 10px; font-size: 2rem; font-weight: 700; }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 22px; }}
    .controls form, .actions form {{ margin: 0; }}
    button {{
      border: 0;
      border-radius: 999px;
      background: var(--accent);
      color: #fff;
      padding: 10px 16px;
      font-size: 0.95rem;
      cursor: pointer;
    }}
    button:hover {{ background: var(--accent-dark); }}
    .layout {{ display: grid; gap: 18px; }}
    section {{ padding: 20px; overflow-x: auto; }}
    section h2 {{ margin: 0 0 14px; font-size: 1.25rem; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 12px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ color: var(--muted); font-size: 0.9rem; letter-spacing: 0.04em; text-transform: uppercase; }}
    .actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .footer {{ margin-top: 16px; color: var(--muted); font-size: 0.92rem; }}
    @media (max-width: 720px) {{
      .hero h1 {{ font-size: 1.8rem; }}
      button {{ width: 100%; }}
      .actions {{ min-width: 190px; }}
    }}
  </style>
</head>
<body>
  <main>
    <div class=\"hero\">
      <h1>Duster Local Demo</h1>
      <p>Interactive browser-based sandbox for the intelligent traffic monitoring system. Trigger accidents, create traffic jams, run monitoring cycles, and inspect drone assignments live in memory.</p>
      {banner}
    </div>

    <div class=\"metrics\">
      <div class=\"metric\"><strong>Routes</strong><span>{report['monitored_routes']}</span></div>
      <div class=\"metric\"><strong>Active Incidents</strong><span>{report['active_incidents']}</span></div>
      <div class=\"metric\"><strong>Deployed Drones</strong><span>{fleet['deployed']}</span></div>
      <div class=\"metric\"><strong>Idle Drones</strong><span>{fleet['idle']}</span></div>
    </div>

    <div class=\"controls\">
      <form method=\"post\"><input type=\"hidden\" name=\"action\" value=\"monitor\"><button type=\"submit\">Run Monitoring Cycle</button></form>
      <form method=\"post\"><input type=\"hidden\" name=\"action\" value=\"recall_all\"><button type=\"submit\">Recall All Drones</button></form>
      <form method=\"post\"><input type=\"hidden\" name=\"action\" value=\"recharge_all\"><button type=\"submit\">Recharge Fleet</button></form>
      <form method=\"post\"><input type=\"hidden\" name=\"action\" value=\"reset_demo\"><button type=\"submit\">Reset Demo</button></form>
    </div>

    <div class=\"layout\">
      <section>
        <h2>Routes</h2>
        <table>
          <thead>
            <tr><th>ID</th><th>Name</th><th>Congestion</th><th>Level</th><th>Accident</th><th>Assigned Drones</th><th>Actions</th></tr>
          </thead>
          <tbody>{route_rows}</tbody>
        </table>
      </section>

      <section>
        <h2>Active Incidents</h2>
        <table>
          <thead>
            <tr><th>Incident ID</th><th>Route</th><th>Type</th><th>Action</th></tr>
          </thead>
          <tbody>{incident_rows}</tbody>
        </table>
      </section>

      <section>
        <h2>Fleet</h2>
        <table>
          <thead>
            <tr><th>Drone</th><th>Status</th><th>Battery</th><th>Assigned Route</th></tr>
          </thead>
          <tbody>{drone_rows}</tbody>
        </table>
      </section>
    </div>

    <div class=\"footer\">Open this page locally, trigger events, and refresh state through the controls above. State is stored in memory and resets when the process restarts.</div>
  </main>
</body>
</html>
"""


def application(
    environ: dict,
    start_response,
) -> Iterable[bytes]:
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()

    if path != "/":
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"Not Found"]

    message = ""
    if method == "POST":
        try:
            message = _handle_action(_read_form_data(environ))
        except Exception as exc:
            message = f"Request failed: {exc}"

    html = _render_dashboard(message)
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
    return [html.encode("utf-8")]


def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the local demo server."""
    with make_server(host, port, application) as server:
        print(f"Duster web demo running at http://{host}:{port}")
        server.serve_forever()


if __name__ == "__main__":
    serve()