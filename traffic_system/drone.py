"""Drone class representing an individual traffic-management drone."""

import logging
from typing import Optional

from traffic_system.constants import (
    BATTERY_DRAIN_DEPLOY,
    BATTERY_DRAIN_MANAGE,
    BATTERY_DRAIN_RETURN,
    MIN_BATTERY_TO_DEPLOY,
)
from traffic_system.models import DroneStatus, Route

logger = logging.getLogger(__name__)


class Drone:
    """A traffic-management drone that can be deployed to roads.

    Drones act as aerial traffic police officers: they can be dispatched
    to accident scenes to manage traffic until human officers arrive, and
    coordinated across congested routes to resolve traffic jams.

    Attributes:
        drone_id: Unique identifier for this drone.
        battery_level: Remaining battery as a percentage (0-100).
        status: Current operational status.
        assigned_route_id: Route this drone is currently serving, if any.
    """

    def __init__(self, drone_id: str, battery_level: int = 100) -> None:
        self.drone_id = drone_id
        self.battery_level = battery_level
        self.status = DroneStatus.IDLE
        self.assigned_route_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if the drone can be deployed on a new mission."""
        return (
            self.status == DroneStatus.IDLE
            and self.battery_level >= MIN_BATTERY_TO_DEPLOY
        )

    def needs_charging(self) -> bool:
        """Return True if the drone's battery is critically low."""
        return self.battery_level < MIN_BATTERY_TO_DEPLOY

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def deploy_to_route(self, route: Route) -> bool:
        """Fly to *route* and begin managing traffic there.

        Args:
            route: The road segment to manage.

        Returns:
            True if deployment succeeded, False otherwise.
        """
        if not self.is_available():
            logger.warning(
                "Drone %s cannot deploy: status=%s battery=%d%%",
                self.drone_id,
                self.status.value,
                self.battery_level,
            )
            return False

        self.status = DroneStatus.DEPLOYED
        self.assigned_route_id = route.route_id
        self.battery_level = max(0, self.battery_level - BATTERY_DRAIN_DEPLOY)
        route.assigned_drones.append(self.drone_id)

        logger.info(
            "Drone %s deployed to route '%s' (battery: %d%%)",
            self.drone_id,
            route.name,
            self.battery_level,
        )
        return True

    def manage_traffic(self, route: Route) -> bool:
        """Perform a traffic-management cycle on *route*.

        The drone directs vehicles, enforces lane discipline, and signals
        drivers — mirroring the role of a traffic police officer.

        Args:
            route: The road segment currently being managed.

        Returns:
            True if management cycle completed successfully.
        """
        if self.status != DroneStatus.DEPLOYED:
            logger.warning(
                "Drone %s is not deployed; cannot manage traffic.", self.drone_id
            )
            return False

        if self.assigned_route_id != route.route_id:
            logger.warning(
                "Drone %s is assigned to route %s, not %s.",
                self.drone_id,
                self.assigned_route_id,
                route.route_id,
            )
            return False

        self.battery_level = max(0, self.battery_level - BATTERY_DRAIN_MANAGE)
        reduction = min(10, route.congestion_score)
        route.congestion_score = max(0, route.congestion_score - reduction)

        logger.info(
            "Drone %s managing traffic on '%s' — congestion reduced to %d (battery: %d%%)",
            self.drone_id,
            route.name,
            route.congestion_score,
            self.battery_level,
        )
        return True

    def return_to_base(self, route: Optional[Route] = None) -> None:
        """Return the drone to its charging station.

        Args:
            route: If provided, the drone is removed from the route's
                   assigned-drone list.
        """
        if route is not None and self.drone_id in route.assigned_drones:
            route.assigned_drones.remove(self.drone_id)

        self.status = DroneStatus.RETURNING
        self.battery_level = max(0, self.battery_level - BATTERY_DRAIN_RETURN)
        self.assigned_route_id = None

        logger.info(
            "Drone %s returning to base (battery: %d%%)",
            self.drone_id,
            self.battery_level,
        )

    def recharge(self) -> None:
        """Recharge the drone battery to full."""
        self.battery_level = 100
        self.status = DroneStatus.IDLE
        logger.info("Drone %s fully recharged.", self.drone_id)

    def __repr__(self) -> str:
        return (
            f"Drone(id={self.drone_id!r}, status={self.status.value}, "
            f"battery={self.battery_level}%, route={self.assigned_route_id!r})"
        )
