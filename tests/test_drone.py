"""Tests for the Drone class."""

import pytest

from traffic_system.drone import Drone
from traffic_system.models import DroneStatus, Route


@pytest.fixture
def idle_drone():
    return Drone("D1", battery_level=100)


@pytest.fixture
def route():
    return Route(route_id="R1", name="Main Street", congestion_score=70)


class TestDroneInitialization:
    def test_default_attributes(self, idle_drone):
        assert idle_drone.drone_id == "D1"
        assert idle_drone.battery_level == 100
        assert idle_drone.status == DroneStatus.IDLE
        assert idle_drone.assigned_route_id is None

    def test_custom_battery(self):
        drone = Drone("D2", battery_level=50)
        assert drone.battery_level == 50


class TestDroneAvailability:
    def test_idle_full_battery_is_available(self, idle_drone):
        assert idle_drone.is_available() is True

    def test_low_battery_not_available(self):
        drone = Drone("D3", battery_level=10)
        assert drone.is_available() is False

    def test_needs_charging_when_low(self):
        drone = Drone("D4", battery_level=10)
        assert drone.needs_charging() is True

    def test_full_battery_not_needs_charging(self, idle_drone):
        assert idle_drone.needs_charging() is False


class TestDroneDeployment:
    def test_successful_deployment(self, idle_drone, route):
        result = idle_drone.deploy_to_route(route)
        assert result is True
        assert idle_drone.status == DroneStatus.DEPLOYED
        assert idle_drone.assigned_route_id == route.route_id
        assert idle_drone.drone_id in route.assigned_drones

    def test_battery_drains_on_deploy(self, idle_drone, route):
        initial = idle_drone.battery_level
        idle_drone.deploy_to_route(route)
        assert idle_drone.battery_level < initial

    def test_already_deployed_cannot_redeploy(self, idle_drone, route):
        idle_drone.deploy_to_route(route)
        route2 = Route("R2", "Side Street")
        result = idle_drone.deploy_to_route(route2)
        assert result is False

    def test_low_battery_drone_cannot_deploy(self, route):
        drone = Drone("D5", battery_level=10)
        result = drone.deploy_to_route(route)
        assert result is False


class TestDroneManageTraffic:
    def test_manage_traffic_reduces_congestion(self, idle_drone, route):
        idle_drone.deploy_to_route(route)
        initial_congestion = route.congestion_score
        idle_drone.manage_traffic(route)
        assert route.congestion_score < initial_congestion

    def test_manage_traffic_drains_battery(self, idle_drone, route):
        idle_drone.deploy_to_route(route)
        before = idle_drone.battery_level
        idle_drone.manage_traffic(route)
        assert idle_drone.battery_level < before

    def test_undeployed_drone_cannot_manage(self, idle_drone, route):
        result = idle_drone.manage_traffic(route)
        assert result is False

    def test_wrong_route_cannot_manage(self, idle_drone):
        route_a = Route("RA", "Route A", congestion_score=50)
        route_b = Route("RB", "Route B", congestion_score=50)
        idle_drone.deploy_to_route(route_a)
        result = idle_drone.manage_traffic(route_b)
        assert result is False


class TestDroneReturnAndRecharge:
    def test_return_to_base(self, idle_drone, route):
        idle_drone.deploy_to_route(route)
        idle_drone.return_to_base(route)
        assert idle_drone.status == DroneStatus.RETURNING
        assert idle_drone.assigned_route_id is None
        assert idle_drone.drone_id not in route.assigned_drones

    def test_recharge_restores_battery(self):
        drone = Drone("D6", battery_level=30)
        drone.recharge()
        assert drone.battery_level == 100
        assert drone.status == DroneStatus.IDLE
