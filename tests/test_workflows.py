"""Tests for Workflows 2, 4, 5 — Gate Change, Equipment Failure, Loading Failure.

All deterministic — no LLM mocking needed.
"""
from datetime import datetime, timezone, timedelta

from src.tools import store
from src.tools.passenger_notify import PassengerNotifyTool
from src.models import (
    Bag, BagStatus, Flight, FlightStatus, LoadPlan, CrewStatus,
    DisruptionEvent, DisruptionType, Severity,
)


def _base_seed():
    store.reset()
    PassengerNotifyTool.clear()
    now = datetime.now(timezone.utc)
    store.FLIGHTS["AA501"] = Flight(
        flight_id="AA501", airline="AA", origin="JFK", destination="LHR",
        scheduled_departure=now + timedelta(minutes=20),
        estimated_departure=now + timedelta(minutes=20),
        gate="B12", terminal="B",
    )
    store.LOAD_PLANS["AA501"] = LoadPlan(
        flight_id="AA501", aircraft_type="B737",
        max_weight_kg=15000.0, current_weight_kg=12000.0, bag_count=85,
    )
    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=3, total_crew=5, active_tasks=1, can_take_exception=True,
    )
    store.CREW_STATUS["C"] = CrewStatus(
        zone="C", available_crew=2, total_crew=4, active_tasks=0, can_take_exception=True,
    )


# ── Playbook matching ─────────────────────────────────────────────────────────

def test_gate_change_playbook_routes_to_new_coordinator():
    from src.tier1.playbooks import match_playbook
    event = DisruptionEvent(
        event_type=DisruptionType.GATE_CHANGE,
        payload={"flight_id": "AA501", "old_gate": "B12", "new_gate": "C4",
                 "old_terminal": "B", "new_terminal": "C"},
        affected_flights=["AA501"],
    )
    pb = match_playbook(event)
    assert pb is not None
    assert pb.name == "GATE_CHANGE"
    assert pb.activate == ["gate_change_coordinator"]
    inputs = pb.build_inputs(event)
    assert "gate_change_coordinator" in inputs
    assert inputs["gate_change_coordinator"]["old_gate"] == "B12"
    assert inputs["gate_change_coordinator"]["new_gate"] == "C4"


def test_bag_not_loaded_playbook_routes_correctly():
    from src.tier1.playbooks import match_playbook
    event = DisruptionEvent(
        event_type=DisruptionType.BAG_NOT_LOADED,
        payload={"bag_tag": "BA-001", "flight_id": "AA501"},
        severity=Severity.HIGH,
        affected_flights=["AA501"],
    )
    pb = match_playbook(event)
    assert pb is not None
    assert pb.name == "BAG_NOT_LOADED"
    assert pb.activate == ["loading_failure_coordinator"]
    inputs = pb.build_inputs(event)
    assert inputs["loading_failure_coordinator"]["bag_tag"] == "BA-001"


def test_equipment_failure_playbook_routes_correctly():
    from src.tier1.playbooks import match_playbook
    event = DisruptionEvent(
        event_type=DisruptionType.EQUIPMENT_FAILURE,
        payload={"equipment_id": "CONV-B3", "zone": "B", "failure_type": "CONVEYOR"},
        severity=Severity.MEDIUM,
        affected_flights=[],
    )
    pb = match_playbook(event)
    assert pb is not None
    assert pb.name == "EQUIPMENT_FAILURE"
    assert pb.activate == ["equipment_coordinator"]
    inputs = pb.build_inputs(event)
    assert inputs["equipment_coordinator"]["failed_zone"] == "B"


# ── Workflow 2: Gate Change ───────────────────────────────────────────────────

def test_gate_change_diverts_bags_in_old_chute():
    """Bags already sorted to old gate chute get diverted to new gate."""
    _base_seed()
    # Seed a bag already sorted to old gate chute
    store.BAGS["BA-GC1"] = Bag(
        bag_tag="BA-GC1", passenger_id="P901", passenger_name="Test Pax",
        origin_flight="AA401", destination_flight="AA501",
        final_destination="LHR", current_location="CHUTE_B12",
    )

    from src.tier2.gate_change_coordinator import build_gate_change_coordinator
    result = build_gate_change_coordinator().compile().invoke({
        "disruption_id": "d-gc-001",
        "flight_id": "AA501",
        "old_gate": "B12",
        "new_gate": "C4",
        "old_terminal": "B",
        "new_terminal": "C",
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "find_affected_bags" in node_names
    assert "divert_bags" in node_names
    assert "reassign_crew" in node_names
    assert "update_load_plan" in node_names
    assert "notify_ops" in node_names

    # Bag should be rerouted away from old chute
    assert "CHUTE_B12" not in store.BAGS["BA-GC1"].current_location


def test_gate_change_same_terminal_not_cross_terminal():
    _base_seed()
    from src.tier2.gate_change_coordinator import build_gate_change_coordinator
    result = build_gate_change_coordinator().compile().invoke({
        "disruption_id": "d-gc-002",
        "flight_id": "AA501",
        "old_gate": "B12", "new_gate": "B15",
        "old_terminal": "B", "new_terminal": "B",
        "actions_taken": [],
    })
    assert result.get("cross_terminal") is False


# ── Workflow 5: Loading Failure ───────────────────────────────────────────────

def test_loading_failure_emergency_load_when_flight_at_gate():
    """Bag not loaded but flight still at gate → emergency load dispatched."""
    _base_seed()
    store.BAGS["BA-LF1"] = Bag(
        bag_tag="BA-LF1", passenger_id="P801", passenger_name="Late Bag",
        origin_flight="AA501", destination_flight=None,
        final_destination="LHR", current_location="BHS_ZONE_B",
    )

    from src.tier2.loading_failure_coordinator import build_loading_failure_coordinator
    result = build_loading_failure_coordinator().compile().invoke({
        "disruption_id": "d-lf-001",
        "bag_tag": "BA-LF1",
        "flight_id": "AA501",
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "locate_bag" in node_names
    assert "check_flight" in node_names
    # 20-min window > 10-min minimum → emergency load path
    assert "emergency_load" in node_names
    assert result.get("flight_at_gate") is True


def test_loading_failure_rebooks_when_flight_departed():
    """Flight already departed → bag rebooked on next available."""
    store.reset()
    PassengerNotifyTool.clear()
    now = datetime.now(timezone.utc)
    # Flight departed 5 min ago
    store.FLIGHTS["AA501"] = Flight(
        flight_id="AA501", airline="AA", origin="JFK", destination="LHR",
        scheduled_departure=now - timedelta(minutes=5),
        estimated_departure=now - timedelta(minutes=5),
        gate="B12", terminal="B", status=FlightStatus.DEPARTED,
    )
    store.BAGS["BA-LF2"] = Bag(
        bag_tag="BA-LF2", passenger_id="P802", passenger_name="Missed Load",
        origin_flight="AA501", destination_flight=None,
        final_destination="LHR", current_location="BHS_ZONE_B",
    )
    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=3, total_crew=5, active_tasks=0, can_take_exception=True
    )

    from src.tier2.loading_failure_coordinator import build_loading_failure_coordinator
    result = build_loading_failure_coordinator().compile().invoke({
        "disruption_id": "d-lf-002",
        "bag_tag": "BA-LF2",
        "flight_id": "AA501",
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "rebook_bag" in node_names
    assert result.get("flight_at_gate") is False
    assert result.get("rebooked") is True
    # Bag should be marked as MISSED
    assert store.BAGS["BA-LF2"].status == BagStatus.MISSED
    # Passenger should be notified
    sent = PassengerNotifyTool.get_sent()
    assert any(n["bag_tag"] == "BA-LF2" for n in sent)


# ── Workflow 4: Equipment Failure ─────────────────────────────────────────────

def test_equipment_failure_reroutes_impacted_bags():
    """Belt failure in Zone B → bags rerouted to alternate zone."""
    _base_seed()
    # Seed bags in the failed zone
    for i, tag in enumerate(["BA-EQ1", "BA-EQ2"]):
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=f"P70{i}", passenger_name=f"Equip Pax {i}",
            origin_flight="AA401", destination_flight="AA501",
            final_destination="LHR", current_location="BHS_ZONE_B",
        )

    from src.tier2.equipment_coordinator import build_equipment_coordinator
    result = build_equipment_coordinator().compile().invoke({
        "disruption_id": "d-eq-001",
        "equipment_id": "CONV-B3",
        "failed_zone": "B",
        "failure_type": "CONVEYOR",
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "find_impacted_bags" in node_names
    assert "reroute_bags" in node_names
    assert "alert_maintenance" in node_names
    assert "assess_impact" in node_names
    assert result.get("maintenance_alerted") is True

    # Bags should be moved out of Zone B
    for tag in ["BA-EQ1", "BA-EQ2"]:
        assert "ZONE_B" not in store.BAGS[tag].current_location


def test_equipment_failure_raises_maintenance_alert():
    """Maintenance alert is always raised regardless of bag rerouting outcome."""
    _base_seed()
    initial_log_len = len(store.ACTION_LOG)

    from src.tier2.equipment_coordinator import build_equipment_coordinator
    build_equipment_coordinator().compile().invoke({
        "disruption_id": "d-eq-002",
        "equipment_id": "SCAN-C1",
        "failed_zone": "C",
        "failure_type": "SCANNER",
        "actions_taken": [],
    })

    maintenance_alerts = [
        a for a in store.ACTION_LOG[initial_log_len:]
        if a.get("action") == "raise_alert"
    ]
    assert len(maintenance_alerts) == 1
    assert maintenance_alerts[0]["equipment_id"] == "SCAN-C1"
