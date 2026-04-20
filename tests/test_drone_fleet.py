"""Tests for the DroneFleet class."""

import pytest

from traffic_system.drone import Drone
from traffic_system.drone_fleet import DroneFleet
from traffic_system.models import DroneStatus, Route


@pytest.fixture
def fleet_with_three_drones():
    fleet = DroneFleet()
    fleet.add_drone(Drone("D1"))
    fleet.add_drone(Drone("D2"))
    fleet.add_drone(Drone("D3"))
    return fleet


@pytest.fixture
def accident_route():
    return Route(route_id="R_ACC", name="Highway 1", congestion_score=90, has_accident=True)


@pytest.fixture
def congested_routes():
    return [
        Route(route_id="R1", name="North Ave", congestion_score=85),
        Route(route_id="R2", name="South Blvd", congestion_score=80),
    ]


class TestFleetManagement:
    def test_add_drone_increases_size(self):
        fleet = DroneFleet()
        assert len(fleet) == 0
        fleet.add_drone(Drone("D1"))
        assert len(fleet) == 1

    def test_remove_drone(self):
        fleet = DroneFleet()
        fleet.add_drone(Drone("D1"))
        removed = fleet.remove_drone("D1")
        assert removed is not None
        assert removed.drone_id == "D1"
        assert len(fleet) == 0

    def test_remove_nonexistent_drone_returns_none(self):
        fleet = DroneFleet()
        assert fleet.remove_drone("ghost") is None

    def test_available_drones(self, fleet_with_three_drones):
        available = fleet_with_three_drones.available_drones()
        assert len(available) == 3

    def test_low_battery_drone_not_available(self):
        fleet = DroneFleet()
        fleet.add_drone(Drone("D_low", battery_level=5))
        assert len(fleet.available_drones()) == 0


class TestAccidentDeployment:
    def test_deploys_to_accident(self, fleet_with_three_drones, accident_route):
        result = fleet_with_three_drones.deploy_to_accident(accident_route)
        assert result.success is True
        assert len(result.deployed_drones) >= 1

    def test_accident_route_has_assigned_drone(self, fleet_with_three_drones, accident_route):
        fleet_with_three_drones.deploy_to_accident(accident_route)
        assert len(accident_route.assigned_drones) >= 1

    def test_empty_fleet_fails(self, accident_route):
        fleet = DroneFleet()
        result = fleet.deploy_to_accident(accident_route)
        assert result.success is False
        assert result.deployed_drones == []

    def test_deployed_drone_status_is_deployed(self, fleet_with_three_drones, accident_route):
        result = fleet_with_three_drones.deploy_to_accident(accident_route)
        deployed_id = result.deployed_drones[0]
        drone = next(d for d in fleet_with_three_drones.drones if d.drone_id == deployed_id)
        assert drone.status == DroneStatus.DEPLOYED


class TestTrafficJamDeployment:
    def test_deploys_across_multiple_routes(self, fleet_with_three_drones, congested_routes):
        result = fleet_with_three_drones.deploy_to_traffic_jam(congested_routes)
        assert result.success is True
        assert len(result.deployed_drones) >= 1

    def test_each_route_gets_a_drone(self, fleet_with_three_drones, congested_routes):
        fleet_with_three_drones.deploy_to_traffic_jam(congested_routes)
        for route in congested_routes:
            assert len(route.assigned_drones) >= 1

    def test_empty_routes_list_fails(self, fleet_with_three_drones):
        result = fleet_with_three_drones.deploy_to_traffic_jam([])
        assert result.success is False

    def test_no_available_drones_fails(self, congested_routes):
        fleet = DroneFleet()
        fleet.add_drone(Drone("D_low", battery_level=5))
        result = fleet.deploy_to_traffic_jam(congested_routes)
        assert result.success is False


class TestFleetRecallAndStatus:
    def test_recall_all_returns_drones(self, fleet_with_three_drones, accident_route):
        fleet_with_three_drones.deploy_to_accident(accident_route, drones_needed=2)
        fleet_with_three_drones.recall_all({"R_ACC": accident_route})
        statuses = {d.status for d in fleet_with_three_drones.drones}
        assert DroneStatus.DEPLOYED not in statuses

    def test_recharge_all(self):
        fleet = DroneFleet()
        fleet.add_drone(Drone("D1", battery_level=40))
        fleet.add_drone(Drone("D2", battery_level=30))
        fleet.recharge_all()
        for drone in fleet.drones:
            assert drone.battery_level == 100

    def test_fleet_status_summary(self, fleet_with_three_drones):
        status = fleet_with_three_drones.fleet_status()
        assert status["total"] == 3
        assert status["idle"] == 3
