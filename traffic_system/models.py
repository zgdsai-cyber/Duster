"""Core data models for the traffic monitoring system."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class IncidentType(Enum):
    """Types of traffic incidents the system handles."""

    ACCIDENT = auto()
    TRAFFIC_JAM = auto()


class DroneStatus(Enum):
    """Operational status of a drone."""

    IDLE = "idle"
    DEPLOYED = "deployed"
    RETURNING = "returning"
    CHARGING = "charging"


class CongestionLevel(Enum):
    """Traffic congestion severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Route:
    """Represents a city road segment monitored by the system.

    Attributes:
        route_id: Unique identifier for the route.
        name: Human-readable route name.
        congestion_score: Congestion level on a 0-100 scale.
        has_accident: Whether an active accident is on this route.
        capacity: Maximum vehicle capacity of the route.
        assigned_drones: IDs of drones currently managing this route.
    """

    route_id: str
    name: str
    congestion_score: int = 0
    has_accident: bool = False
    capacity: int = 100
    assigned_drones: list = field(default_factory=list)

    def congestion_level(self) -> CongestionLevel:
        """Return the categorical congestion level for this route."""
        from traffic_system.constants import (
            CONGESTION_HIGH,
            CONGESTION_LOW,
            CONGESTION_MEDIUM,
        )

        if self.congestion_score >= CONGESTION_HIGH:
            return CongestionLevel.CRITICAL
        if self.congestion_score >= CONGESTION_MEDIUM:
            return CongestionLevel.HIGH
        if self.congestion_score >= CONGESTION_LOW:
            return CongestionLevel.MEDIUM
        return CongestionLevel.LOW

    def is_congested(self) -> bool:
        """Return True if the route has significant congestion."""
        from traffic_system.constants import CONGESTION_MEDIUM

        return self.congestion_score >= CONGESTION_MEDIUM


@dataclass
class Incident:
    """A traffic incident that requires drone intervention.

    Attributes:
        incident_id: Unique identifier for the incident.
        incident_type: The category of incident.
        route_id: Route where the incident occurred.
        description: Optional human-readable description.
        resolved: Whether the incident has been resolved.
    """

    incident_id: str
    incident_type: IncidentType
    route_id: str
    description: Optional[str] = None
    resolved: bool = False

    def resolve(self) -> None:
        """Mark this incident as resolved."""
        self.resolved = True


@dataclass
class DroneDeploymentResult:
    """Result of a drone deployment operation.

    Attributes:
        success: Whether the deployment succeeded.
        deployed_drones: IDs of drones that were deployed.
        message: Human-readable result message.
    """

    success: bool
    deployed_drones: list
    message: str
