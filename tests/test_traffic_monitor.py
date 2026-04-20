"""Tests for the TrafficMonitoringSystem."""

import pytest

from traffic_system.drone import Drone
from traffic_system.models import CongestionLevel, DroneStatus, IncidentType, Route
from traffic_system.traffic_monitor import TrafficMonitoringSystem


@pytest.fixture
def system():
    tms = TrafficMonitoringSystem()
    for i in range(1, 5):
        tms.add_drone(Drone(f"D{i}"))
    return tms


@pytest.fixture
def clear_route():
    return Route(route_id="R_CLEAR", name="Clear Road", congestion_score=10)


@pytest.fixture
def congested_route():
    return Route(route_id="R_CONG", name="Congested Ave", congestion_score=85)


@pytest.fixture
def accident_route():
    return Route(route_id="R_ACC", name="Crash Street", congestion_score=50, has_accident=True)


class TestSystemSetup:
    def test_add_route(self, system, clear_route):
        system.add_route(clear_route)
        assert "R_CLEAR" in system.routes

    def test_add_drone_increases_fleet(self):
        tms = TrafficMonitoringSystem()
        tms.add_drone(Drone("D_extra"))
        assert len(tms.fleet) == 1

    def test_unknown_route_raises(self, system):
        with pytest.raises(ValueError, match="Unknown route_id"):
            system.report_incident("NONEXISTENT", IncidentType.ACCIDENT)


class TestIncidentReporting:
    def test_report_accident_sets_flag(self, system, accident_route):
        accident_route.has_accident = False
        system.add_route(accident_route)
        system.report_incident("R_ACC", IncidentType.ACCIDENT)
        assert system.routes["R_ACC"].has_accident is True

    def test_report_accident_deploys_drone(self, system, clear_route):
        system.add_route(clear_route)
        system.report_incident("R_CLEAR", IncidentType.ACCIDENT)
        assert len(clear_route.assigned_drones) >= 1

    def test_report_traffic_jam_sets_congestion(self, system, clear_route):
        system.add_route(clear_route)
        system.report_incident("R_CLEAR", IncidentType.TRAFFIC_JAM)
        assert system.routes["R_CLEAR"].congestion_score >= 60

    def test_active_incidents_tracked(self, system, clear_route):
        system.add_route(clear_route)
        incident = system.report_incident("R_CLEAR", IncidentType.ACCIDENT)
        assert incident.incident_id in system.active_incidents

    def test_resolve_incident(self, system, clear_route):
        system.add_route(clear_route)
        incident = system.report_incident("R_CLEAR", IncidentType.ACCIDENT)
        resolved = system.resolve_incident(incident.incident_id)
        assert resolved is True
        assert incident.incident_id not in system.active_incidents

    def test_resolve_accident_clears_flag(self, system, clear_route):
        system.add_route(clear_route)
        incident = system.report_incident("R_CLEAR", IncidentType.ACCIDENT)
        system.resolve_incident(incident.incident_id)
        assert system.routes["R_CLEAR"].has_accident is False

    def test_resolve_unknown_returns_false(self, system):
        assert system.resolve_incident("no-such-id") is False


class TestMonitoringCycle:
    def test_monitor_detects_accident(self, system, accident_route):
        system.add_route(accident_route)
        results = system.monitor()
        assert "R_ACC" in results
        assert results["R_ACC"].success is True

    def test_monitor_detects_congestion(self, system, congested_route):
        system.add_route(congested_route)
        results = system.monitor()
        assert "R_CONG" in results
        assert results["R_CONG"].success is True

    def test_monitor_ignores_clear_routes(self, system, clear_route):
        system.add_route(clear_route)
        results = system.monitor()
        assert "R_CLEAR" not in results

    def test_monitor_handles_multiple_routes(self, system):
        for i in range(3):
            system.add_route(Route(f"R{i}", f"Route {i}", congestion_score=85))
        results = system.monitor()
        assert len(results) > 0


class TestStatusReport:
    def test_status_report_structure(self, system, congested_route, accident_route):
        system.add_route(congested_route)
        system.add_route(accident_route)
        report = system.status_report()
        assert "monitored_routes" in report
        assert "active_incidents" in report
        assert "congested_routes" in report
        assert "accident_routes" in report
        assert "fleet" in report

    def test_status_report_counts_routes(self, system):
        for i in range(3):
            system.add_route(Route(f"SR{i}", f"Street {i}"))
        report = system.status_report()
        assert report["monitored_routes"] == 3


class TestCongestionLevels:
    def test_low_congestion(self):
        route = Route("R", "R", congestion_score=10)
        assert route.congestion_level() == CongestionLevel.LOW

    def test_medium_congestion(self):
        route = Route("R", "R", congestion_score=40)
        assert route.congestion_level() == CongestionLevel.MEDIUM

    def test_high_congestion(self):
        route = Route("R", "R", congestion_score=65)
        assert route.congestion_level() == CongestionLevel.HIGH

    def test_critical_congestion(self):
        route = Route("R", "R", congestion_score=90)
        assert route.congestion_level() == CongestionLevel.CRITICAL

    def test_is_congested_true(self):
        route = Route("R", "R", congestion_score=70)
        assert route.is_congested() is True

    def test_is_congested_false(self):
        route = Route("R", "R", congestion_score=20)
        assert route.is_congested() is False
