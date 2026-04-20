# Duster — Intelligent Traffic Monitoring System

An intelligent traffic monitoring system for city roads that analyses the causes of congestion and intervenes autonomously to regulate traffic flow.

## Overview

The system is linked to a fleet of drones that act as aerial traffic officers. It responds to two main incident types:

| Incident | System Response |
|----------|-----------------|
| **Accident** | Drones are automatically deployed to manage traffic until human officers arrive. |
| **Traffic Jam** | Drones are coordinated across affected routes and work together to resolve congestion. |

## Architecture

```
traffic_system/
├── constants.py        # Tuneable thresholds and rates
├── models.py           # Route, Incident, DroneStatus, CongestionLevel, DroneDeploymentResult
├── drone.py            # Individual drone (deploy, manage traffic, return, recharge)
├── drone_fleet.py      # Fleet coordinator (accident & traffic-jam deployments)
└── traffic_monitor.py  # Main system controller (monitoring cycle, incident reporting)
```

## Quick Start

```python
from traffic_system import TrafficMonitoringSystem, Drone, Route, IncidentType

# Build the system
system = TrafficMonitoringSystem()

# Register city roads
system.add_route(Route("R1", "Main Street"))
system.add_route(Route("R2", "Highway 5", congestion_score=85))

# Add drones to the fleet
for i in range(1, 4):
    system.add_drone(Drone(f"D{i}"))

# Report an accident — drones deploy automatically
incident = system.report_incident("R1", IncidentType.ACCIDENT)

# Run a full monitoring cycle (detects accidents & congestion)
results = system.monitor()

# Resolve the accident when human officers arrive
system.resolve_incident(incident.incident_id)

# Check system status
print(system.status_report())
```

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## Local Web Demo

You can also try the system in a browser using the built-in demo server:

```bash
python -m traffic_system.webapp
```

Then open http://127.0.0.1:8000 to:

- trigger accident and traffic-jam incidents on sample routes
- run a monitoring cycle manually
- resolve incidents and inspect live fleet status
- reset the in-memory demo state