"""AI-powered traffic analysis using Groq (free LLM) + TomTom Traffic Flow API (free tier).

Flow:
  1. fetch_traffic_data()  → calls TomTom for each route's real-time speed/density.
  2. analyze_with_ai()     → sends traffic snapshot to Groq (Llama 3) and gets
                             deployment decisions as structured JSON.
  3. execute_decisions()   → applies the AI decisions to the TrafficMonitoringSystem.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config holder (populated at runtime via the UI settings panel)
# ---------------------------------------------------------------------------

_config: Dict[str, str] = {
    "groq_api_key": "",
    "tomtom_api_key": "",
}

_last_ai_result: Dict[str, Any] = {
    "timestamp": None,
    "traffic_snapshot": [],
    "decisions": [],
    "raw_response": "",
    "error": None,
    "groq_model": "llama-3.1-8b-instant",
}


def configure(groq_api_key: str, tomtom_api_key: str) -> None:
    """Set API keys at runtime (never stored to disk)."""
    _config["groq_api_key"] = groq_api_key.strip()
    _config["tomtom_api_key"] = tomtom_api_key.strip()


def is_configured() -> bool:
    return bool(_config["groq_api_key"] and _config["tomtom_api_key"])


def get_last_result() -> Dict[str, Any]:
    return dict(_last_ai_result)


# ---------------------------------------------------------------------------
# TomTom Traffic Flow API
# ---------------------------------------------------------------------------

TOMTOM_FLOW_URL = (
    "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
)


def fetch_route_traffic(lat: float, lon: float, tomtom_key: str) -> Dict[str, Any]:
    """Fetch real-time traffic flow data for a single (lat, lon) point.

    Returns a dict with keys: current_speed, free_flow_speed, confidence,
    road_closure, congestion_ratio.
    Raises requests.RequestException on network/API failure.
    """
    params = {
        "point": f"{lat},{lon}",
        "key": tomtom_key,
        "unit": "KMPH",
        "openLr": "false",
    }
    resp = requests.get(TOMTOM_FLOW_URL, params=params, timeout=8)
    resp.raise_for_status()
    data = resp.json().get("flowSegmentData", {})
    current_speed = data.get("currentSpeed", 0)
    free_flow = data.get("freeFlowSpeed", 1) or 1
    ratio = max(0.0, min(1.0, current_speed / free_flow))
    # congestion_score: 0 = free flow, 100 = standstill
    congestion_score = round((1 - ratio) * 100)
    return {
        "current_speed_kmh": current_speed,
        "free_flow_speed_kmh": free_flow,
        "confidence": data.get("confidence", 0),
        "road_closure": data.get("roadClosure", False),
        "congestion_score": congestion_score,
    }


def fetch_traffic_data(city_routes: List[Dict]) -> List[Dict]:
    """Fetch TomTom traffic data for all routes in the city.

    Args:
        city_routes: list of route dicts from city_data.py (must have lat/lon).

    Returns:
        List of dicts with route_id, name, congestion_score, and raw TomTom fields.
    """
    tomtom_key = _config["tomtom_api_key"]
    results = []
    for route in city_routes:
        lat = route.get("lat")
        lon = route.get("lon")
        if lat is None or lon is None:
            continue
        try:
            tm = fetch_route_traffic(lat, lon, tomtom_key)
            results.append({
                "route_id": route["id"],
                "name": route["name"],
                **tm,
            })
        except Exception as exc:
            logger.warning("TomTom fetch failed for %s: %s", route["id"], exc)
            results.append({
                "route_id": route["id"],
                "name": route["name"],
                "current_speed_kmh": None,
                "free_flow_speed_kmh": None,
                "confidence": 0,
                "road_closure": False,
                "congestion_score": None,
                "error": str(exc),
            })
    return results


# ---------------------------------------------------------------------------
# Groq LLM
# ---------------------------------------------------------------------------

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"  # stable free-tier model (April 2026)

_SYSTEM_PROMPT = """\
You are an expert autonomous traffic management AI controlling a drone fleet in a smart city.
You receive real-time traffic data for city roads and the current drone fleet status.
Your job: decide how to deploy or recall drones on each route to maximise safety and traffic flow.

Rules:
- If road_closure is true OR congestion_score >= 80 → action must be "deploy_accident"
- If congestion_score >= 55 AND congestion_score < 80 → action should be "deploy_jam"
- If congestion_score < 55 AND no road closure → action should be "recall" (free drone)
- "none" → no change needed (score < 30 and no issues)
- Always provide a short Arabic reason (سبب) for each decision.

You MUST respond with ONLY a valid JSON array, no markdown, no extra text.
Example:
[
  {"route_id": "R1", "action": "deploy_accident", "reason": "إغلاق الطريق وازدحام حاد"},
  {"route_id": "R2", "action": "deploy_jam", "reason": "كثافة مرورية عالية 72%"},
  {"route_id": "R3", "action": "recall", "reason": "حركة مرور سلسة"},
  {"route_id": "R4", "action": "none", "reason": "لا تدخل مطلوب"}
]
"""


def _build_user_message(traffic_snapshot: List[Dict], fleet_status: Dict) -> str:
    lines = ["=== بيانات حركة المرور الآنية ==="]
    for r in traffic_snapshot:
        score = r.get("congestion_score", "N/A")
        speed = r.get("current_speed_kmh", "N/A")
        free = r.get("free_flow_speed_kmh", "N/A")
        closure = "نعم ⚠️" if r.get("road_closure") else "لا"
        err = r.get("error", "")
        if err:
            lines.append(
                f"- {r['name']} ({r['route_id']}): بيانات غير متاحة ({err})"
            )
        else:
            lines.append(
                f"- {r['name']} ({r['route_id']}): "
                f"ازدحام={score}/100 | سرعة={speed} كم/س | "
                f"سرعة حرة={free} كم/س | إغلاق={closure}"
            )

    lines.append("\n=== حالة الأسطول ===")
    lines.append(
        f"جاهزة: {fleet_status.get('idle', 0)} | "
        f"منتشرة: {fleet_status.get('deployed', 0)} | "
        f"عائدة: {fleet_status.get('returning', 0)} | "
        f"الإجمالي: {fleet_status.get('total', 0)}"
    )
    lines.append("\nأعطِ قرارك لكل طريق بالتنسيق JSON المطلوب فقط.")
    return "\n".join(lines)


def _extract_json(text: str) -> List[Dict]:
    """Extract the first JSON array from the LLM response text."""
    text = text.strip()
    # Try direct parse first
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    # Find array in text
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not extract JSON array from response: {text[:200]}")


def analyze_with_ai(
    traffic_snapshot: List[Dict],
    fleet_status: Dict,
) -> List[Dict]:
    """Send traffic snapshot to Groq and return a list of drone deployment decisions.

    Each decision: {"route_id": str, "action": str, "reason": str}
    Actions: deploy_accident | deploy_jam | recall | none
    """
    groq_key = _config["groq_api_key"]
    if not groq_key:
        raise RuntimeError("Groq API key not configured.")

    user_msg = _build_user_message(traffic_snapshot, fleet_status)

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0.2,
        "max_tokens": 512,
    }
    headers = {
        "Authorization": f"Bearer {groq_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(GROQ_CHAT_URL, json=payload, headers=headers, timeout=20)
    if not resp.ok:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise RuntimeError(
            f"Groq API error {resp.status_code}: {detail}"
        )
    raw = resp.json()["choices"][0]["message"]["content"]
    return _extract_json(raw), raw


# ---------------------------------------------------------------------------
# Execute AI decisions on the TrafficMonitoringSystem
# ---------------------------------------------------------------------------

from traffic_system.models import IncidentType


def execute_decisions(
    decisions: List[Dict],
    system,          # TrafficMonitoringSystem
) -> List[Dict]:
    """Apply AI decisions to the live traffic monitoring system.

    Returns a list of execution results.
    """
    results = []
    for dec in decisions:
        route_id = dec.get("route_id", "")
        action = dec.get("action", "none")
        reason = dec.get("reason", "")

        if route_id not in system.routes:
            results.append({"route_id": route_id, "action": action, "status": "unknown_route"})
            continue

        if action == "deploy_accident":
            inc = system.report_incident(route_id, IncidentType.ACCIDENT,
                                         description=f"AI: {reason}")
            results.append({
                "route_id": route_id, "action": action,
                "status": "deployed", "incident_id": inc.incident_id,
            })

        elif action == "deploy_jam":
            inc = system.report_incident(route_id, IncidentType.TRAFFIC_JAM,
                                         description=f"AI: {reason}")
            results.append({
                "route_id": route_id, "action": action,
                "status": "deployed", "incident_id": inc.incident_id,
            })

        elif action == "recall":
            route = system.routes[route_id]
            # Resolve any open incidents on this route
            for inc in list(system.active_incidents.values()):
                if inc.route_id == route_id:
                    system.resolve_incident(inc.incident_id)
            results.append({"route_id": route_id, "action": action, "status": "recalled"})

        else:  # none
            results.append({"route_id": route_id, "action": action, "status": "no_change"})

    return results


# ---------------------------------------------------------------------------
# Main entry: full AI cycle
# ---------------------------------------------------------------------------

def run_ai_cycle(city_routes: List[Dict], system) -> Dict[str, Any]:
    """Run one full AI cycle: fetch traffic → analyse → execute → return result."""
    global _last_ai_result

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    result: Dict[str, Any] = {
        "timestamp": timestamp,
        "traffic_snapshot": [],
        "decisions": [],
        "execution": [],
        "raw_response": "",
        "error": None,
    }

    # 1. Fetch traffic
    try:
        snapshot = fetch_traffic_data(city_routes)
        result["traffic_snapshot"] = snapshot
    except Exception as exc:
        result["error"] = f"Traffic fetch error: {exc}"
        _last_ai_result = result
        return result

    # 2. Analyse with AI
    try:
        fleet_status = system.status_report()["fleet"]
        decisions, raw = analyze_with_ai(snapshot, fleet_status)
        result["decisions"] = decisions
        result["raw_response"] = raw
    except Exception as exc:
        result["error"] = f"AI analysis error: {exc}"
        _last_ai_result = result
        return result

    # 3. Execute
    try:
        execution = execute_decisions(decisions, system)
        result["execution"] = execution
    except Exception as exc:
        result["error"] = f"Execution error: {exc}"

    _last_ai_result = result
    return result
