"""DroneFleet — manages a collection of drones working cooperatively."""

import logging
from typing import List, Optional

from traffic_system.constants import DRONES_PER_JAM_ROUTE, HUMAN_OFFICER_ETA_MINUTES
from traffic_system.drone import Drone
from traffic_system.models import DroneDeploymentResult, Route

logger = logging.getLogger(__name__)


class DroneFleet:
    """Coordinates a fleet of drones for city-wide traffic management.

    The fleet handles two main scenarios:
    - **Accidents**: dispatch the minimum number of drones needed to
      control the scene until human officers arrive.
    - **Traffic jams**: coordinate drones across multiple congested
      routes to collectively resolve congestion.
    """

    def __init__(self, drones: Optional[List[Drone]] = None) -> None:
        self._drones: List[Drone] = drones if drones is not None else []

    # ------------------------------------------------------------------
    # Fleet management
    # ------------------------------------------------------------------

    def add_drone(self, drone: Drone) -> None:
        """Add *drone* to the fleet."""
        self._drones.append(drone)
        logger.info("Drone %s added to fleet.", drone.drone_id)

    def remove_drone(self, drone_id: str) -> Optional[Drone]:
        """Remove and return the drone with *drone_id*, or None."""
        for i, drone in enumerate(self._drones):
            if drone.drone_id == drone_id:
                return self._drones.pop(i)
        return None

    @property
    def drones(self) -> List[Drone]:
        """All drones in the fleet (read-only view)."""
        return list(self._drones)

    def available_drones(self) -> List[Drone]:
        """Return drones that are ready to be deployed."""
        return [d for d in self._drones if d.is_available()]

    def deployed_drones(self) -> List[Drone]:
        """Return drones currently on active missions."""
        from traffic_system.models import DroneStatus

        return [d for d in self._drones if d.status == DroneStatus.DEPLOYED]

    # ------------------------------------------------------------------
    # Deployment operations
    # ------------------------------------------------------------------

    def deploy_to_accident(
        self, route: Route, drones_needed: int = 1
    ) -> DroneDeploymentResult:
        """Deploy drones to an accident scene to manage traffic.

        Drones act as aerial traffic officers and direct vehicles around
        the accident until human officers arrive (estimated
        ``HUMAN_OFFICER_ETA_MINUTES`` minutes).

        Args:
            route: The route where the accident occurred.
            drones_needed: Minimum number of drones to deploy.

        Returns:
            A :class:`~traffic_system.models.DroneDeploymentResult`
            describing the outcome.
        """
        available = self.available_drones()
        if not available:
            msg = (
                f"No available drones to deploy to accident on '{route.name}'. "
                "Human officers must respond directly."
            )
            logger.warning(msg)
            return DroneDeploymentResult(success=False, deployed_drones=[], message=msg)

        to_deploy = available[:drones_needed]
        deployed_ids: List[str] = []
        for drone in to_deploy:
            if drone.deploy_to_route(route):
                deployed_ids.append(drone.drone_id)

        if deployed_ids:
            msg = (
                f"{len(deployed_ids)} drone(s) [{', '.join(deployed_ids)}] deployed to "
                f"accident on '{route.name}'. Managing traffic until human officers "
                f"arrive (~{HUMAN_OFFICER_ETA_MINUTES} min)."
            )
            logger.info(msg)
            return DroneDeploymentResult(
                success=True, deployed_drones=deployed_ids, message=msg
            )

        msg = f"Deployment to accident on '{route.name}' failed; drones unavailable."
        logger.error(msg)
        return DroneDeploymentResult(success=False, deployed_drones=[], message=msg)

    def deploy_to_traffic_jam(self, congested_routes: List[Route]) -> DroneDeploymentResult:
        """Coordinate drones across multiple congested routes to resolve a jam.

        Each route receives up to ``DRONES_PER_JAM_ROUTE`` drones.  The
        drones work together — each one managing its assigned segment —
        to provide a comprehensive solution that alleviates congestion
        across the whole network.

        Args:
            congested_routes: Routes requiring drone assistance.

        Returns:
            A :class:`~traffic_system.models.DroneDeploymentResult`
            describing the outcome.
        """
        if not congested_routes:
            return DroneDeploymentResult(
                success=False,
                deployed_drones=[],
                message="No congested routes provided.",
            )

        available = self.available_drones()
        if not available:
            msg = "No available drones to address traffic jam."
            logger.warning(msg)
            return DroneDeploymentResult(success=False, deployed_drones=[], message=msg)

        deployed_ids: List[str] = []
        drone_iter = iter(available)

        for route in congested_routes:
            for _ in range(DRONES_PER_JAM_ROUTE):
                drone = next(drone_iter, None)
                if drone is None:
                    break
                if drone.deploy_to_route(route):
                    deployed_ids.append(drone.drone_id)

        if deployed_ids:
            route_names = ", ".join(f"'{r.name}'" for r in congested_routes)
            msg = (
                f"{len(deployed_ids)} drone(s) [{', '.join(deployed_ids)}] coordinated "
                f"across routes: {route_names}. Working together to resolve congestion."
            )
            logger.info(msg)
            return DroneDeploymentResult(
                success=True, deployed_drones=deployed_ids, message=msg
            )

        msg = "Traffic-jam deployment failed; no drones could be dispatched."
        logger.error(msg)
        return DroneDeploymentResult(success=False, deployed_drones=[], message=msg)

    def recall_all(self, routes_by_id: Optional[dict] = None) -> None:
        """Return all deployed drones to base.

        Args:
            routes_by_id: Optional mapping of route_id → Route so that
                          drones can be removed from their route's list.
        """
        from traffic_system.models import DroneStatus

        for drone in self._drones:
            if drone.status == DroneStatus.DEPLOYED:
                route = None
                if routes_by_id and drone.assigned_route_id:
                    route = routes_by_id.get(drone.assigned_route_id)
                drone.return_to_base(route)

    def recharge_all(self) -> None:
        """Recharge every drone in the fleet."""
        for drone in self._drones:
            drone.recharge()

    def fleet_status(self) -> dict:
        """Return a summary of the fleet's current state."""
        from traffic_system.models import DroneStatus

        summary: dict = {s.value: 0 for s in DroneStatus}
        for drone in self._drones:
            summary[drone.status.value] += 1
        summary["total"] = len(self._drones)
        return summary

    def __len__(self) -> int:
        return len(self._drones)

    def __repr__(self) -> str:
        return f"DroneFleet(size={len(self._drones)}, available={len(self.available_drones())})"
