"""Flask web application for the Duster traffic monitoring demo.

Run:
    python -m traffic_system.app
Then open http://127.0.0.1:5000
"""

import json
import math
import random
import threading
import time
from typing import Dict

from flask import Flask, jsonify, render_template_string, request

from traffic_system import Drone, IncidentType, Route, TrafficMonitoringSystem
from traffic_system.city_data import CITIES, get_city, get_city_keys
import traffic_system.traffic_ai as traffic_ai

# ---------------------------------------------------------------------------
# State – one TrafficMonitoringSystem per city, kept in memory
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_systems: Dict[str, TrafficMonitoringSystem] = {}
_drone_positions: Dict[str, Dict] = {}   # city -> {drone_id: {lat, lon}}
_current_city: str = "riyadh"


def _build_system(city_key: str) -> TrafficMonitoringSystem:
    city = get_city(city_key)
    system = TrafficMonitoringSystem()
    for rd in city["routes"]:
        route = Route(
            route_id=rd["id"],
            name=rd["name"],
            congestion_score=rd["congestion_score"],
        )
        system.add_route(route)
    for i in range(1, city["drones"] + 1):
        system.add_drone(Drone(f"D{i}"))
    return system


def _init_drone_positions(city_key: str, system: TrafficMonitoringSystem) -> Dict:
    city = get_city(city_key)
    blat = city["base_lat"]
    blon = city["base_lon"]
    positions = {}
    for i, drone in enumerate(system.fleet.drones):
        angle = (2 * math.pi * i) / max(len(system.fleet.drones), 1)
        positions[drone.drone_id] = {
            "lat": round(blat + 0.003 * math.cos(angle), 6),
            "lon": round(blon + 0.003 * math.sin(angle), 6),
        }
    return positions


def _get_system(city_key: str) -> TrafficMonitoringSystem:
    if city_key not in _systems:
        _systems[city_key] = _build_system(city_key)
        _drone_positions[city_key] = _init_drone_positions(
            city_key, _systems[city_key]
        )
    return _systems[city_key]


def _route_midpoint_latlon(city_key: str, route_id: str):
    city = get_city(city_key)
    for rd in city["routes"]:
        if rd["id"] == route_id:
            coords = rd.get("coords", [])
            if coords:
                mid = coords[len(coords) // 2]
                return mid[0], mid[1]
            return rd.get("lat", city["base_lat"]), rd.get("lon", city["base_lon"])
    return city["base_lat"], city["base_lon"]


def _update_drone_positions(city_key: str):
    """Move drone icons toward their assigned route midpoints (lat/lon)."""
    system = _systems.get(city_key)
    if not system:
        return
    city_data = get_city(city_key)
    blat = city_data["base_lat"]
    blon = city_data["base_lon"]
    pos = _drone_positions.get(city_key, {})
    for drone in system.fleet.drones:
        cur = pos.get(drone.drone_id, {"lat": blat, "lon": blon})
        if drone.assigned_route_id:
            tlat, tlon = _route_midpoint_latlon(city_key, drone.assigned_route_id)
        else:
            tlat, tlon = blat, blon
        # Ease 20% toward target + tiny jitter for realism
        nlat = cur["lat"] + (tlat - cur["lat"]) * 0.20 + random.uniform(-0.0002, 0.0002)
        nlon = cur["lon"] + (tlon - cur["lon"]) * 0.20 + random.uniform(-0.0002, 0.0002)
        pos[drone.drone_id] = {"lat": round(nlat, 6), "lon": round(nlon, 6)}
    _drone_positions[city_key] = pos


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

HTML = r"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Duster – نظام مراقبة المرور</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    :root {
      --bg: #0f1923; --panel: rgba(255,255,255,0.05);
      --border: rgba(255,255,255,0.10); --ink: #e8ecef;
      --muted: #8fa3b1; --accent: #00c6ff; --accent2: #e06c00;
      --ok: #30d47a; --warn: #f5c518; --danger: #ff4d4d;
      --deployed: #00c6ff; --idle: #30d47a; --returning: #f5c518;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', Tahoma, sans-serif; background: var(--bg); color: var(--ink); min-height: 100vh; }
    header {
      background: linear-gradient(90deg, #0d2137, #0f2e1e);
      padding: 14px 28px; display: flex; align-items: center; gap: 16px;
      border-bottom: 1px solid var(--border);
    }
    header h1 { font-size: 1.5rem; color: var(--accent); }
    header p  { color: var(--muted); font-size: 0.9rem; }
    .city-select {
      margin-right: auto; display: flex; align-items: center; gap: 8px;
    }
    .city-select label { color: var(--muted); font-size: 0.9rem; }
    .city-select select {
      background: rgba(0,198,255,0.1); color: var(--ink); border: 1px solid var(--accent);
      border-radius: 8px; padding: 6px 12px; font-size: 0.95rem; cursor: pointer;
    }
    .layout { display: grid; grid-template-columns: 1fr 420px; height: calc(100vh - 68px); }
    .map-panel { position: relative; overflow: hidden; border-left: 1px solid var(--border); }
    #leaflet-map { width: 100%; height: 100%; display: block; z-index: 0; }
    .sidebar { overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 14px; background: #0d1e2d; }

    .card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 14px; flex-shrink: 0; }
    .card h2 { font-size: 1rem; color: var(--accent); margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }

    .metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .metric { background: rgba(255,255,255,0.04); border-radius: 10px; padding: 10px; text-align: center; }
    .metric strong { display: block; font-size: 0.78rem; color: var(--muted); text-transform: uppercase; }
    .metric span { display: block; font-size: 1.6rem; font-weight: 700; margin-top: 4px; }

    .btn-group { display: flex; flex-direction: column; gap: 8px; }
    button {
      border: 0; border-radius: 8px; padding: 9px 14px; font-size: 0.9rem; cursor: pointer;
      font-family: inherit; transition: filter 0.15s;
    }
    button:hover { filter: brightness(1.2); }
    .btn-primary { background: var(--accent); color: #0f1923; font-weight: 700; }
    .btn-warn    { background: var(--warn); color: #0f1923; }
    .btn-danger  { background: var(--danger); color: #fff; }
    .btn-muted   { background: rgba(255,255,255,0.08); color: var(--ink); }

    /* Route list */
    #routes-card { max-height: 340px; overflow-y: auto; min-height: 120px; }
    .route-item {
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px 14px;
      margin-bottom: 10px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .route-item:last-child { margin-bottom: 0; }
    .route-header { display: flex; align-items: center; gap: 10px; }
    .route-dot { width: 14px; height: 14px; border-radius: 50%; flex-shrink: 0; }
    .route-name { flex: 1; font-size: 1rem; font-weight: 600; }
    .route-score {
      font-weight: 700; font-size: 1.1rem; min-width: 36px; text-align: center;
      background: rgba(255,255,255,0.07); border-radius: 8px; padding: 2px 8px;
    }
    .route-bar-wrap { background: rgba(255,255,255,0.08); border-radius: 999px; height: 8px; overflow: hidden; }
    .route-bar { height: 100%; border-radius: 999px; transition: width 0.4s; }
    .route-meta { display: flex; align-items: center; gap: 8px; font-size: 0.82rem; color: var(--muted); }
    .route-btns { display: flex; gap: 8px; }
    .route-btns button { flex: 1; padding: 8px 0; font-size: 0.88rem; border-radius: 8px; font-weight: 600; }

    /* Drone list */
    .drone-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 0.88rem; }
    .drone-item:last-child { border-bottom: 0; }
    .drone-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
    .drone-name { flex: 1; }
    .drone-batt { font-size: 0.82rem; color: var(--muted); }

    /* Incidents */
    .incident-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 0.85rem; }
    .incident-item:last-child { border-bottom: 0; }
    .incident-type { font-weight: 700; flex: 1; }
    .badge { border-radius: 6px; padding: 2px 8px; font-size: 0.78rem; font-weight: 700; }
    .badge-accident { background: var(--danger); color: #fff; }
    .badge-jam      { background: var(--warn); color: #0f1923; }

    /* Toast */
    #toast {
      position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
      background: rgba(0,198,255,0.9); color: #0f1923; font-weight: 700;
      padding: 10px 24px; border-radius: 999px; font-size: 0.92rem;
      opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 100;
    }
    #toast.show { opacity: 1; }

    @keyframes drone-pulse { 0%,100%{box-shadow:0 0 0 0 rgba(0,198,255,.6)} 50%{box-shadow:0 0 0 10px rgba(0,198,255,0)} }
    .drone-pulse-css { animation: drone-pulse 1.4s ease-in-out infinite; }

    @media (max-width: 1000px) {
      .layout { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
      .map-panel { order: 2; min-height: 55vw; }
      .sidebar { order: 1; max-height: 50vh; }
    }
  </style>
</head>
<body>
<header>
  <div>
    <h1>🚁 Duster</h1>
    <p>نظام مراقبة المرور الذكي بالطائرات المسيّرة</p>
  </div>
  <div class="city-select">
    <label for="city-picker">المدينة:</label>
    <select id="city-picker" onchange="changeCity(this.value)">
      {% for key, city in cities.items() %}
      <option value="{{ key }}" {% if key == current_city %}selected{% endif %}>{{ city.label }}</option>
      {% endfor %}
    </select>
  </div>
</header>

<div class="layout">
  <div class="map-panel">
    <div id="leaflet-map"></div>
  </div>

    <div class="sidebar">
      <!-- AI Settings -->
      <div class="card">
        <div style="display:flex;align-items:center;gap:10px">
          <span id="ai-status-dot" style="width:12px;height:12px;border-radius:50%;background:var(--danger);flex-shrink:0"></span>
          <span id="ai-status-text" style="flex:1;font-size:.9rem;color:var(--muted)">الذكاء الاصطناعي غير مُهيَّأ</span>
          <button class="btn-muted" style="padding:5px 12px;font-size:.82rem" onclick="toggleSettings()">⚙️ إعداد</button>
        </div>
        <div id="settings-panel" style="display:none;margin-top:12px;display:none">
          <p style="font-size:.8rem;color:var(--muted);margin-bottom:8px">
            🔑 <a href="https://console.groq.com" target="_blank" style="color:var(--accent)">Groq (مجاني)</a> +
            <a href="https://developer.tomtom.com" target="_blank" style="color:var(--accent)">TomTom (مجاني)</a>
          </p>
          <input id="groq-key" type="password" placeholder="Groq API Key" style="width:100%;background:rgba(255,255,255,0.06);border:1px solid var(--border);border-radius:8px;padding:8px 10px;color:var(--ink);font-size:.88rem;margin-bottom:8px;font-family:inherit">
          <input id="tomtom-key" type="password" placeholder="TomTom API Key" style="width:100%;background:rgba(255,255,255,0.06);border:1px solid var(--border);border-radius:8px;padding:8px 10px;color:var(--ink);font-size:.88rem;margin-bottom:8px;font-family:inherit">
          <button class="btn-primary" style="width:100%" onclick="saveKeys()">💾 حفظ المفاتيح</button>
        </div>
      </div>

      <!-- AI Run + Results -->
      <div class="card">
        <h2>🤖 الذكاء الاصطناعي</h2>
        <button id="ai-run-btn" class="btn-primary" style="width:100%;margin-bottom:12px" onclick="runAiCycle()">🤖 تشغيل الذكاء الاصطناعي</button>
        <p style="font-size:.8rem;color:var(--muted);margin-bottom:10px">يجلب حالة الطريق لحظياً من TomTom ثم يحللها بـ Llama 3 عبر Groq ويوجّه الدرونات تلقائياً.</p>
        <div id="ai-result-body"><p style="color:var(--muted);font-size:.85rem">لا يوجد تحليل بعد.</p></div>
      </div>
    <div class="card">
      <h2>📊 حالة النظام</h2>
      <div class="metrics">
        <div class="metric"><strong>الطرق</strong><span id="m-routes">-</span></div>
        <div class="metric"><strong>حوادث نشطة</strong><span id="m-incidents" style="color:var(--danger)">-</span></div>
        <div class="metric"><strong>درونات منتشرة</strong><span id="m-deployed" style="color:var(--accent)">-</span></div>
        <div class="metric"><strong>جاهزة</strong><span id="m-idle" style="color:var(--ok)">-</span></div>
      </div>
    </div>

    <div class="card">
      <h2>🎛️ تحكم</h2>
      <div class="btn-group">
        <button class="btn-primary" onclick="runMonitor()">▶ تشغيل دورة المراقبة</button>
        <button class="btn-warn"    onclick="recallAll()">↩ استدعاء جميع الدرونات</button>
        <button class="btn-muted"   onclick="rechargeAll()">🔋 إعادة شحن الأسطول</button>
        <button class="btn-danger"  onclick="resetCity()">↺ إعادة تعيين المدينة</button>
      </div>
    </div>

    <div class="card" id="routes-card">
      <h2>🛣️ الطرق</h2>
      <div id="routes-list"></div>
    </div>

    <div class="card">
      <h2>🚨 الحوادث النشطة</h2>
      <div id="incidents-list"></div>
    </div>

    <div class="card">
      <h2>🚁 الأسطول</h2>
      <div id="drones-list"></div>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
const CITY_DATA = {{ city_data_json|safe }};
let _leafletMap = null;
let _routeLayers = [];
let _droneLayers = {};
let currentCity = "{{ current_city }}";
let state = null;
let autoRefresh = null;

// ---------- City change ----------
function changeCity(key) {
  currentCity = key;
  fetch('/api/city', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({city: key})
  })
  .then(r => r.json())
  .then(() => { tick(); toast('تم تحميل مدينة جديدة'); });
}

// ---------- Controls ----------
function runMonitor() {
  apiPost('/api/monitor').then(() => toast('تمت دورة المراقبة'));
}
function recallAll() {
  apiPost('/api/recall').then(() => toast('تم استدعاء الدرونات'));
}
function rechargeAll() {
  apiPost('/api/recharge').then(() => toast('تمت إعادة الشحن'));
}
function resetCity() {
  apiPost('/api/reset').then(() => toast('تمت إعادة التعيين'));
}
function reportIncident(routeId, type) {
  apiPost('/api/incident', {route_id: routeId, type: type}).then(() =>
    toast(`تم الإبلاغ عن حادث على الطريق ${routeId}`)
  );
}
function resolveIncident(incidentId) {
  apiPost('/api/resolve', {incident_id: incidentId}).then(() =>
    toast('تم حل الحادث')
  );
}

function apiPost(url, body = {}) {
  return fetch(url, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body)
  }).then(r => r.json()).then(r => { state = r; render(); return r; });
}

// ---------- Auto tick ----------
function tick() {
  fetch('/api/state?city=' + currentCity)
    .then(r => r.json())
    .then(r => { state = r; render(); });
}
function startAutoRefresh() {
  if (autoRefresh) clearInterval(autoRefresh);
  autoRefresh = setInterval(tick, 1800);
}

// ---------- Render ----------
function render() {
  if (!state) return;
  renderMetrics();
  renderRoutes();
  renderIncidents();
  renderDroneList();
  renderMap();
}

function renderMetrics() {
  document.getElementById('m-routes').textContent    = state.routes.length;
  document.getElementById('m-incidents').textContent = state.incidents.length;
  document.getElementById('m-deployed').textContent  = state.fleet.deployed;
  document.getElementById('m-idle').textContent      = state.fleet.idle;
}

// ---------- congestion helpers ----------
const CONGESTION_COLOUR = score =>
  score >= 80 ? '#ff4d4d' :
  score >= 60 ? '#e06c00' :
  score >= 30 ? '#f5c518' : '#30d47a';

const CONGESTION_CLASS = score =>
  score >= 80 ? 'congestion-critical' :
  score >= 60 ? 'congestion-high'     :
  score >= 30 ? 'congestion-medium'   : 'congestion-low';

const CONGESTION_LABEL = score =>
  score >= 80 ? 'حرج' :
  score >= 60 ? 'كثيف' :
  score >= 30 ? 'متوسط' : 'سلس';

// ---------- Leaflet map ----------
function initLeafletMap() {
  const cityMeta = CITY_DATA[currentCity] || {};
  const center = state.city_center || cityMeta.center || [24.688, 46.683];
  const zoom   = state.city_zoom   || cityMeta.zoom   || 12;

  if (_leafletMap) {
    _leafletMap.remove();
    _leafletMap = null;
  }
  _routeLayers = [];
  _droneLayers = {};

  _leafletMap = L.map('leaflet-map', {
    center: center,
    zoom: zoom,
    zoomControl: true,
  });

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(_leafletMap);
}

let _lastCity = null;
function renderMap() {
  const cityMeta = CITY_DATA[currentCity] || {};
  const cityRoutes = cityMeta.routes || [];

  // Re-initialise map if city changed or not yet created
  if (!_leafletMap || _lastCity !== currentCity) {
    initLeafletMap();
    _lastCity = currentCity;
  }

  const routeStateMap = {};
  (state.routes || []).forEach(r => routeStateMap[r.id] = r);

  // Clear old route layers
  _routeLayers.forEach(l => _leafletMap.removeLayer(l));
  _routeLayers = [];

  cityRoutes.forEach(rd => {
    const rs = routeStateMap[rd.id] || {};
    const score  = rs.congestion_score ?? rd.congestion_score;
    const colour = CONGESTION_COLOUR(score);
    const weight = rs.has_accident ? 10 : 6;
    const coords = rd.coords || [];

    if (coords.length >= 2) {
      const poly = L.polyline(coords, {
        color: colour, weight: weight, opacity: 0.9,
      }).addTo(_leafletMap);
      poly.bindTooltip(`${rd.name}  ${score}/100`, {sticky: true, direction: 'top'});
      _routeLayers.push(poly);
    }

    // Accident marker at midpoint
    if (rs.has_accident && coords.length) {
      const mid = coords[Math.floor(coords.length / 2)];
      const marker = L.marker(mid, {
        icon: L.divIcon({
          html: '<span style="font-size:22px">🚨</span>',
          className: '', iconAnchor: [11, 11],
        }),
      }).addTo(_leafletMap);
      marker.bindTooltip('حادث على ' + rd.name);
      _routeLayers.push(marker);
    }
  });

  // Drone markers
  Object.keys(_droneLayers).forEach(id => _leafletMap.removeLayer(_droneLayers[id]));
  _droneLayers = {};

  (state.drones || []).forEach(drone => {
    const pos = state.drone_positions[drone.id];
    if (!pos) return;
    const colour =
      drone.status === 'deployed'  ? '#00c6ff' :
      drone.status === 'returning' ? '#f5c518' :
      drone.status === 'charging'  ? '#a0aec0' : '#30d47a';
    const pulse = drone.status === 'deployed' ? 'drone-pulse-css' : '';
    const icon = L.divIcon({
      html: `<div class="${pulse}" style="width:32px;height:32px;border-radius:50%;background:${colour};border:2px solid #fff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#0f1923;box-shadow:0 2px 6px rgba(0,0,0,.5)">${drone.id}</div>`,
      className: '',
      iconSize: [32, 32],
      iconAnchor: [16, 16],
    });
    const m = L.marker([pos.lat, pos.lon], {icon}).addTo(_leafletMap);
    m.bindTooltip(`${drone.id} — ${drone.status} 🔋${drone.battery}%`);
    _droneLayers[drone.id] = m;
  });
}

// ---------- Side panels ----------
function renderRoutes() {
  const el = document.getElementById('routes-list');
  if (!state.routes.length) { el.innerHTML = '<p style="color:var(--muted);font-size:.85rem">لا توجد طرق</p>'; return; }
  el.innerHTML = state.routes.map(r => {
    const col = CONGESTION_COLOUR(r.congestion_score);
    const lbl = CONGESTION_LABEL(r.congestion_score);
    const accidentBadge = r.has_accident
      ? `<span style="color:var(--danger);font-weight:700">🚨 حادث</span>` : '';
    const dronesBadge = r.assigned_drones && r.assigned_drones.length
      ? `<span>🚁 ${r.assigned_drones.join(', ')}</span>` : '';
    return `
    <div class="route-item">
      <div class="route-header">
        <div class="route-dot" style="background:${col}"></div>
        <span class="route-name">${r.name}</span>
        <span class="route-score" style="color:${col}">${r.congestion_score}</span>
      </div>
      <div class="route-bar-wrap">
        <div class="route-bar" style="width:${r.congestion_score}%;background:${col}"></div>
      </div>
      <div class="route-meta">
        <span style="color:${col};font-weight:600">${lbl}</span>
        ${accidentBadge}
        ${dronesBadge}
      </div>
      <div class="route-btns">
        <button class="btn-danger" onclick="reportIncident('${r.id}','ACCIDENT')">🚨 إبلاغ حادث</button>
        <button class="btn-warn"   onclick="reportIncident('${r.id}','TRAFFIC_JAM')">🚗 إبلاغ ازدحام</button>
      </div>
    </div>`;
  }).join('');
}

function renderIncidents() {
  const el = document.getElementById('incidents-list');
  if (!state.incidents.length) {
    el.innerHTML = '<p style="color:var(--muted);font-size:.85rem">لا توجد حوادث نشطة</p>';
    return;
  }
  el.innerHTML = state.incidents.map(inc => `
    <div class="incident-item">
      <span class="badge ${inc.type === 'ACCIDENT' ? 'badge-accident' : 'badge-jam'}">
        ${inc.type === 'ACCIDENT' ? '🚨 حادث' : '🚗 ازدحام'}
      </span>
      <span class="incident-type">${inc.route_id}</span>
      <button class="btn-muted" style="font-size:.78rem;padding:3px 8px" onclick="resolveIncident('${inc.id}')">حل</button>
    </div>
  `).join('');
}

function renderDroneList() {
  const el = document.getElementById('drones-list');
  if (!state.drones.length) { el.innerHTML = '<p>لا توجد درونات</p>'; return; }
  el.innerHTML = state.drones.map(d => {
    const colour =
      d.status === 'deployed'  ? 'var(--accent)' :
      d.status === 'returning' ? 'var(--warn)'   :
      d.status === 'charging'  ? 'var(--muted)'  : 'var(--ok)';
    const statusAr =
      d.status === 'deployed'  ? 'منتشر'  :
      d.status === 'returning' ? 'عائد'   :
      d.status === 'charging'  ? 'يشحن'   : 'جاهز';
    return `<div class="drone-item">
      <div class="drone-dot" style="background:${colour}"></div>
      <span class="drone-name">${d.id}</span>
      <span style="color:${colour};font-size:.82rem">${statusAr}</span>
      <span class="drone-batt">🔋${d.battery}%</span>
      ${d.route ? `<span style="font-size:.78rem;color:var(--muted)">${d.route}</span>` : ''}
    </div>`;
  }).join('');
}

// ---------- AI panel ----------
let aiConfigured = false;

function toggleSettings() {
  const p = document.getElementById('settings-panel');
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
}

function saveKeys() {
  const groq   = document.getElementById('groq-key').value.trim();
  const tomtom = document.getElementById('tomtom-key').value.trim();
  if (!groq || !tomtom) { toast('أدخل كلا المفتاحين'); return; }
  fetch('/api/ai/configure', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({groq_api_key: groq, tomtom_api_key: tomtom})
  })
  .then(r => r.json())
  .then(r => {
    if (r.error) { toast('خطأ: ' + r.error); return; }
    aiConfigured = true;
    document.getElementById('ai-status-dot').style.background = 'var(--ok)';
    document.getElementById('ai-status-text').textContent = 'الذكاء الاصطناعي مُهيَّأ ✓';
    document.getElementById('settings-panel').style.display = 'none';
    toast('تم حفظ المفاتيح بنجاح');
  });
}

function runAiCycle() {
  if (!aiConfigured) { toast('أدخل مفاتيح API أولاً من لوحة الإعدادات'); return; }
  const btn = document.getElementById('ai-run-btn');
  btn.disabled = true;
  btn.textContent = '⏳ جاري التحليل...';
  fetch('/api/ai/run', {method:'POST'})
    .then(r => r.json())
    .then(r => {
      btn.disabled = false;
      btn.textContent = '🤖 تشغيل الذكاء الاصطناعي';
      if (r.error) { toast('خطأ: ' + r.error); return; }
      state = r;
      renderAiResult(r.ai_result);
      render();
      toast('✅ اكتمل تحليل الذكاء الاصطناعي');
    })
    .catch(() => {
      btn.disabled = false;
      btn.textContent = '🤖 تشغيل الذكاء الاصطناعي';
      toast('فشل الاتصال بالخادم');
    });
}

function renderAiResult(result) {
  const el = document.getElementById('ai-result-body');
  if (!result || result.error) {
    el.innerHTML = `<p style="color:var(--danger);font-size:.85rem">${result ? result.error : 'لا يوجد نتيجة'}</p>`;
    return;
  }
  const decisions = result.decisions || [];
  const snapshot  = result.traffic_snapshot || [];
  const snapMap = {};
  snapshot.forEach(s => snapMap[s.route_id] = s);

  const actionAr = a =>
    a === 'deploy_accident' ? '🚨 نشر (حادث)' :
    a === 'deploy_jam'      ? '🚗 نشر (ازدحام)' :
    a === 'recall'          ? '↩ استدعاء' : '✓ لا تدخل';
  const actionCol = a =>
    a === 'deploy_accident' ? 'var(--danger)' :
    a === 'deploy_jam'      ? 'var(--warn)'   :
    a === 'recall'          ? 'var(--accent)' : 'var(--muted)';

  el.innerHTML = [
    `<p style="font-size:.8rem;color:var(--muted);margin-bottom:8px">آخر تحليل: ${result.timestamp}</p>`,
    ...decisions.map(d => {
      const s = snapMap[d.route_id] || {};
      const speed = s.current_speed_kmh != null ? s.current_speed_kmh + ' كم/س' : 'N/A';
      const score = s.congestion_score != null ? s.congestion_score + '/100' : 'N/A';
      return `<div style="background:rgba(255,255,255,0.04);border:1px solid var(--border);border-radius:10px;padding:10px;margin-bottom:8px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">
          <span style="font-weight:700;font-size:.95rem">${d.route_id}</span>
          <span style="color:${actionCol(d.action)};font-weight:600;font-size:.9rem">${actionAr(d.action)}</span>
          <span style="color:var(--muted);font-size:.8rem;margin-right:auto">⚡${score} | 🚗${speed}</span>
        </div>
        <p style="font-size:.82rem;color:var(--ink);margin:0">${d.reason}</p>
      </div>`;
    })
  ].join('');
}

// ---------- Toast ----------
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2800);
}

// ---------- Boot ----------
tick();
startAutoRefresh();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    city_data_json = json.dumps(
        {k: {"label": v["label"], "center": v["center"], "zoom": v["zoom"], "routes": v["routes"]} for k, v in CITIES.items()},
        ensure_ascii=False,
    )
    return render_template_string(
        HTML,
        cities=CITIES,
        current_city=_current_city,
        city_data_json=city_data_json,
    )


@app.route("/api/state")
def api_state():
    city_key = request.args.get("city", _current_city)
    with _lock:
        system = _get_system(city_key)
        _update_drone_positions(city_key)
        return _serialize(city_key, system)


@app.route("/api/city", methods=["POST"])
def api_city():
    global _current_city
    data = request.get_json(force=True) or {}
    city_key = data.get("city", "riyadh")
    if city_key not in CITIES:
        return jsonify({"error": "unknown city"}), 400
    with _lock:
        _current_city = city_key
        system = _get_system(city_key)
        _update_drone_positions(city_key)
        return _serialize(city_key, system)


@app.route("/api/monitor", methods=["POST"])
def api_monitor():
    with _lock:
        system = _get_system(_current_city)
        system.monitor()
        _update_drone_positions(_current_city)
        return _serialize(_current_city, system)


@app.route("/api/incident", methods=["POST"])
def api_incident():
    data = request.get_json(force=True) or {}
    route_id = data.get("route_id", "")
    inc_type = data.get("type", "ACCIDENT")
    with _lock:
        system = _get_system(_current_city)
        try:
            system.report_incident(route_id, IncidentType[inc_type])
        except (ValueError, KeyError) as exc:
            return jsonify({"error": str(exc)}), 400
        _update_drone_positions(_current_city)
        return _serialize(_current_city, system)


@app.route("/api/resolve", methods=["POST"])
def api_resolve():
    data = request.get_json(force=True) or {}
    incident_id = data.get("incident_id", "")
    with _lock:
        system = _get_system(_current_city)
        system.resolve_incident(incident_id)
        _update_drone_positions(_current_city)
        return _serialize(_current_city, system)


@app.route("/api/recall", methods=["POST"])
def api_recall():
    with _lock:
        system = _get_system(_current_city)
        system.fleet.recall_all(system.routes)
        _update_drone_positions(_current_city)
        return _serialize(_current_city, system)


@app.route("/api/recharge", methods=["POST"])
def api_recharge():
    with _lock:
        system = _get_system(_current_city)
        system.fleet.recharge_all()
        _update_drone_positions(_current_city)
        return _serialize(_current_city, system)


@app.route("/api/reset", methods=["POST"])
def api_reset():
    with _lock:
        _systems.pop(_current_city, None)
        _drone_positions.pop(_current_city, None)
        system = _get_system(_current_city)
        return _serialize(_current_city, system)


def _serialize(city_key: str, system: TrafficMonitoringSystem) -> dict:
    routes = [
        {
            "id": r.route_id,
            "name": r.name,
            "congestion_score": r.congestion_score,
            "congestion_level": r.congestion_level().value,
            "has_accident": r.has_accident,
            "assigned_drones": list(r.assigned_drones),
        }
        for r in system.routes.values()
    ]
    incidents = [
        {
            "id": inc.incident_id,
            "type": inc.incident_type.name,
            "route_id": inc.route_id,
            "description": inc.description,
        }
        for inc in system.active_incidents.values()
    ]
    drones = [
        {
            "id": d.drone_id,
            "status": d.status.value,
            "battery": d.battery_level,
            "route": d.assigned_route_id,
        }
        for d in system.fleet.drones
    ]
    city_meta = get_city(city_key)
    return jsonify(
        {
            "routes": routes,
            "incidents": incidents,
            "drones": drones,
            "fleet": system.status_report()["fleet"],
            "drone_positions": _drone_positions.get(city_key, {}),
            "city_center": city_meta["center"],
            "city_zoom": city_meta["zoom"],
        }
    )


@app.route("/api/ai/configure", methods=["POST"])
def api_ai_configure():
    data = request.get_json(force=True) or {}
    groq_key   = data.get("groq_api_key", "").strip()
    tomtom_key = data.get("tomtom_api_key", "").strip()
    if not groq_key or not tomtom_key:
        return jsonify({"error": "كلا المفتاحين مطلوبان"}), 400
    traffic_ai.configure(groq_key, tomtom_key)
    return jsonify({"status": "configured", "configured": traffic_ai.is_configured()})


@app.route("/api/ai/status")
def api_ai_status():
    return jsonify({
        "configured": traffic_ai.is_configured(),
        "last_result": traffic_ai.get_last_result(),
    })


@app.route("/api/ai/run", methods=["POST"])
def api_ai_run():
    if not traffic_ai.is_configured():
        return jsonify({"error": "الذكاء الاصطناعي غير مُهيَّأ. أدخل المفاتيح أولاً."}), 400
    city = get_city(_current_city)
    with _lock:
        system = _get_system(_current_city)
        result = traffic_ai.run_ai_cycle(city["routes"], system)
        _update_drone_positions(_current_city)
    serialized = _serialize(_current_city, system).get_json()
    serialized["ai_result"] = result
    return jsonify(serialized)


def serve(host: str = "0.0.0.0", port: int = 5000, debug: bool = False) -> None:
    print(f"Duster web app running at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    serve()
