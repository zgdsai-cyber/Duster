"""TrafficMonitoringSystem — main controller for city traffic management."""

import logging
import uuid
from typing import Dict, List, Optional

from traffic_system.constants import CONGESTION_HIGH, CONGESTION_MEDIUM
from traffic_system.drone import Drone
from traffic_system.drone_fleet import DroneFleet
from traffic_system.models import (
    DroneDeploymentResult,
    Incident,
    IncidentType,
    Route,
)

logger = logging.getLogger(__name__)


class TrafficMonitoringSystem:
    """Intelligent traffic monitoring system for city roads.

    The system continuously analyses road conditions and automatically
    deploys drone assets to:

    - **Accidents** — drones are dispatched immediately to act as aerial
      traffic officers until human responders arrive.
    - **Traffic jams** — drones are coordinated across affected routes
      to collectively resolve congestion.

    Usage example::

        system = TrafficMonitoringSystem()
        system.add_drone(Drone("D1"))
        system.add_drone(Drone("D2"))

        route = Route("R1", "Main Street")
        system.add_route(route)

        # Simulate a reported accident
        system.report_incident("R1", IncidentType.ACCIDENT)

        # Run a monitoring cycle
        system.monitor()
    """

    def __init__(self) -> None:
        self._routes: Dict[str, Route] = {}
        self._fleet = DroneFleet()
        self._incidents: Dict[str, Incident] = {}

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def add_route(self, route: Route) -> None:
        """Register *route* with the monitoring system."""
        self._routes[route.route_id] = route
        logger.info("Route '%s' (%s) added to monitoring.", route.name, route.route_id)

    def add_drone(self, drone: Drone) -> None:
        """Add *drone* to the system's fleet."""
        self._fleet.add_drone(drone)

    # ------------------------------------------------------------------
    # Public queries
    # ------------------------------------------------------------------

    @property
    def routes(self) -> Dict[str, Route]:
        """All monitored routes, keyed by route_id."""
        return dict(self._routes)

    @property
    def fleet(self) -> DroneFleet:
        """The drone fleet managed by this system."""
        return self._fleet

    @property
    def active_incidents(self) -> Dict[str, Incident]:
        """All unresolved incidents."""
        return {k: v for k, v in self._incidents.items() if not v.resolved}

    # ------------------------------------------------------------------
    # Incident reporting
    # ------------------------------------------------------------------

    def report_incident(
        self,
        route_id: str,
        incident_type: IncidentType,
        description: Optional[str] = None,
    ) -> Incident:
        """Report a new incident on *route_id* and trigger a response.

        Args:
            route_id: The route where the incident occurred.
            incident_type: Whether this is an ACCIDENT or TRAFFIC_JAM.
            description: Optional human-readable detail.

        Returns:
            The created :class:`~traffic_system.models.Incident`.

        Raises:
            ValueError: If *route_id* is not registered.
        """
        if route_id not in self._routes:
            raise ValueError(f"Unknown route_id: {route_id!r}")

        incident_id = str(uuid.uuid4())
        incident = Incident(
            incident_id=incident_id,
            incident_type=incident_type,
            route_id=route_id,
            description=description,
        )
        self._incidents[incident_id] = incident
        route = self._routes[route_id]

        logger.info(
            "Incident reported — type=%s route='%s' id=%s",
            incident_type.name,
            route.name,
            incident_id,
        )

        if incident_type == IncidentType.ACCIDENT:
            route.has_accident = True
            self._handle_accident(route)
        else:
            if route.congestion_score < CONGESTION_MEDIUM:
                route.congestion_score = CONGESTION_MEDIUM
            self._handle_traffic_jam([route])

        return incident

    def resolve_incident(self, incident_id: str) -> bool:
        """Mark *incident_id* as resolved and recall its drones.

        Args:
            incident_id: ID of the incident to resolve.

        Returns:
            True if the incident was found and resolved, False otherwise.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            logger.warning("resolve_incident: unknown incident_id %r", incident_id)
            return False

        if incident.resolved:
            logger.info("Incident %r is already resolved.", incident_id)
            return True

        incident.resolve()
        route = self._routes.get(incident.route_id)
        if route and incident.incident_type == IncidentType.ACCIDENT:
            route.has_accident = False

        logger.info("Incident %r resolved.", incident_id)
        return True

    # ------------------------------------------------------------------
    # Monitoring cycle
    # ------------------------------------------------------------------

    def monitor(self) -> Dict[str, DroneDeploymentResult]:
        """Scan all routes and autonomously respond to detected problems.

        The monitoring cycle:
        1. Checks every route for accidents → deploys drones immediately.
        2. Identifies congested routes → coordinates drone fleet across them.

        Returns:
            A mapping of route_id → deployment result for every route
            that required intervention this cycle.
        """
        results: Dict[str, DroneDeploymentResult] = {}

        accident_routes = [r for r in self._routes.values() if r.has_accident]
        jam_routes = [
            r
            for r in self._routes.values()
            if not r.has_accident and r.congestion_score >= CONGESTION_HIGH
        ]

        for route in accident_routes:
            result = self._handle_accident(route)
            results[route.route_id] = result

        if jam_routes:
            result = self._handle_traffic_jam(jam_routes)
            for route in jam_routes:
                results[route.route_id] = result

        if not results:
            logger.info("Monitoring cycle complete — all routes clear.")

        return results

    # ------------------------------------------------------------------
    # Internal response handlers
    # ------------------------------------------------------------------

    def _handle_accident(self, route: Route) -> DroneDeploymentResult:
        """Dispatch drones to an accident scene on *route*."""
        logger.info(
            "ACCIDENT detected on '%s' — deploying drones.", route.name
        )
        return self._fleet.deploy_to_accident(route, drones_needed=1)

    def _handle_traffic_jam(self, congested_routes: List[Route]) -> DroneDeploymentResult:
        """Coordinate fleet deployment across all *congested_routes*."""
        names = [r.name for r in congested_routes]
        logger.info(
            "TRAFFIC JAM detected on [%s] — coordinating drone fleet.",
            ", ".join(names),
        )
        return self._fleet.deploy_to_traffic_jam(congested_routes)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def status_report(self) -> dict:
        """Return a snapshot of the system's current state."""
        congested = [
            r.route_id
            for r in self._routes.values()
            if r.congestion_score >= CONGESTION_MEDIUM
        ]
        accident_routes = [
            r.route_id for r in self._routes.values() if r.has_accident
        ]
        return {
            "monitored_routes": len(self._routes),
            "active_incidents": len(self.active_incidents),
            "congested_routes": congested,
            "accident_routes": accident_routes,
            "fleet": self._fleet.fleet_status(),
        }
