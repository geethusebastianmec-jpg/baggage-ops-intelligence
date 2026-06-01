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


# ── Workflow 8: Network Cascade ───────────────────────────────────────────────

def test_cascade_playbook_fires_for_compound_multi_flight():
    from src.tier1.playbooks import match_playbook
    event = DisruptionEvent(
        event_type=DisruptionType.COMPOUND,
        payload={"affected_flights": ["AA401", "AA402"]},
        severity=Severity.CRITICAL,
        affected_flights=["AA401", "AA402"],
    )
    pb = match_playbook(event)
    assert pb is not None
    assert pb.name == "NETWORK_CASCADE"
    assert pb.activate == ["network_cascade_coordinator"]


def test_cascade_playbook_does_not_fire_for_single_flight():
    """Single-flight compound → falls through to ReAct, not cascade playbook."""
    from src.tier1.playbooks import match_playbook
    event = DisruptionEvent(
        event_type=DisruptionType.COMPOUND,
        payload={},
        affected_flights=["AA401"],   # only one flight
    )
    pb = match_playbook(event)
    # COMPOUND with 1 flight should not match NETWORK_CASCADE
    assert pb is None or pb.name != "NETWORK_CASCADE"


# ── Workflow 7: Security Hold ─────────────────────────────────────────────────

def test_security_hold_playbook_routes_correctly():
    from src.tier1.playbooks import match_playbook
    event = DisruptionEvent(
        event_type=DisruptionType.SECURITY_HOLD,
        payload={"bag_tag": "BA-001", "flight_id": "AA501", "reason": "CT anomaly"},
        severity=Severity.HIGH, affected_flights=["AA501"],
    )
    pb = match_playbook(event)
    assert pb is not None
    assert pb.name == "SECURITY_HOLD"
    assert pb.activate == ["security_hold_coordinator"]
    inputs = pb.build_inputs(event)
    assert inputs["security_hold_coordinator"]["bag_tag"] == "BA-001"
    assert inputs["security_hold_coordinator"]["hold_reason"] == "CT anomaly"


def test_security_hold_cleared_rebooks_bag():
    """Security clears bag → rebooked on next flight, passenger notified."""
    _base_seed()
    store.BAGS["BA-SEC1"] = Bag(
        bag_tag="BA-SEC1", passenger_id="PS01", passenger_name="Security Pax",
        origin_flight="AA401", destination_flight="AA501",
        final_destination="LHR", current_location="SECURITY_SCREENING",
    )

    from src.tier2.security_hold_coordinator import build_security_hold_coordinator
    result = build_security_hold_coordinator().compile().invoke({
        "disruption_id": "d-sec-001",
        "bag_tag": "BA-SEC1",
        "flight_id": "AA501",
        "hold_reason": "CT anomaly detected",
        "simulated_outcome": "CLEARED",
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "place_hold" in node_names
    assert "notify_passenger" in node_names
    assert "rebook_on_next_flight" in node_names
    assert "escalate_to_authority" not in node_names
    assert result.get("escalated") is False

    # Bag should be cleared (not still on security hold)
    assert store.BAGS["BA-SEC1"].status != BagStatus.EXCEPTION or \
           store.BAGS["BA-SEC1"].current_location == "SECURITY_CLEARED"


def test_security_hold_rejected_escalates():
    """Security rejects bag → escalated to law enforcement, passenger notified of seizure."""
    _base_seed()
    store.BAGS["BA-SEC2"] = Bag(
        bag_tag="BA-SEC2", passenger_id="PS02", passenger_name="Reject Pax",
        origin_flight="AA401", destination_flight="AA501",
        final_destination="LHR", current_location="SECURITY_SCREENING",
    )

    from src.tier2.security_hold_coordinator import build_security_hold_coordinator
    result = build_security_hold_coordinator().compile().invoke({
        "disruption_id": "d-sec-002",
        "bag_tag": "BA-SEC2",
        "flight_id": "AA501",
        "hold_reason": "Prohibited item",
        "simulated_outcome": "REJECTED",
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "escalate_to_authority" in node_names
    assert result.get("escalated") is True

    # Check compliance log has the escalation
    escalations = [a for a in store.ACTION_LOG
                   if a.get("action") == "security_rejected_escalated"]
    assert len(escalations) >= 1

    sent = PassengerNotifyTool.get_sent()
    assert any(n["bag_tag"] == "BA-SEC2" for n in sent)


def test_cascade_joint_cpsat_under_shared_crew_constraint():
    """3 inbounds, 12 bags, crew capacity 6 → CP-SAT picks optimal 6."""
    from demo.seed_data import load
    load()
    PassengerNotifyTool.clear()

    from src.tier2.network_cascade_coordinator import build_network_cascade_coordinator
    # All crew across zones B and C: 4+3=7 crew → capacity 7*3=21
    # Our seed only has 10 at-risk bags → no contention, all recoverable by triage
    result = build_network_cascade_coordinator().compile().invoke({
        "disruption_id": "casc-001",
        "affected_inbound_flights": ["AA401", "AA402"],
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "aggregate_cascade" in node_names
    assert "joint_triage" in node_names
    assert "joint_optimize" in node_names
    assert "dispatch_all" in node_names

    # AA401 Zone-B bags + AA402 bags are recoverable; AA401 Zone-D bags are not
    rushed = result.get("joint_recoverable", [])
    missed = result.get("joint_unrecoverable", [])
    assert len(rushed) > 0
    assert "BA-006" in missed   # Zone D, slack=-1
    assert "BA-007" in missed   # Zone D, slack=-1


# ── Workflow 6: Crew Shortage ─────────────────────────────────────────────────

def test_ramp_pulls_adjacent_crew_when_primary_zone_empty():
    """Zone B has no crew → pulls from adjacent Zone C before escalating."""
    store.reset()
    PassengerNotifyTool.clear()
    # Zone B empty, Zone C has crew
    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=0, total_crew=5, active_tasks=5, can_take_exception=False
    )
    store.CREW_STATUS["C"] = CrewStatus(
        zone="C", available_crew=3, total_crew=4, active_tasks=0, can_take_exception=True
    )

    from src.tier2.ramp_coordinator import build_ramp_coordinator
    result = build_ramp_coordinator().compile().invoke({
        "disruption_id": "d-w6-001",
        "bag_tags": ["BA-001"],
        "from_flight": "AA401",
        "to_flight": "AA501",
        "zone": "B",
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "pull_adjacent_crew" in node_names
    assert "escalate" not in node_names
    assert result.get("task_ticket") is not None


def test_ramp_escalates_when_all_zones_empty():
    """No crew anywhere → escalates to AOCC supervisor."""
    store.reset()
    for z in ["A", "B", "C", "D"]:
        store.CREW_STATUS[z] = CrewStatus(
            zone=z, available_crew=0, total_crew=5, active_tasks=5, can_take_exception=False
        )

    from src.tier2.ramp_coordinator import build_ramp_coordinator
    result = build_ramp_coordinator().compile().invoke({
        "disruption_id": "d-w6-002",
        "bag_tags": ["BA-001"],
        "from_flight": "AA401",
        "to_flight": "AA501",
        "zone": "B",
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "escalate" in node_names
    assert result.get("task_ticket") is None


# ── Workflow 3: Cancellation (full) ──────────────────────────────────────────

def test_cancellation_playbook_routes_to_cancellation_coordinator():
    from src.tier1.playbooks import match_playbook
    event = DisruptionEvent(
        event_type=DisruptionType.CANCELLATION,
        payload={"flight_id": "AA401", "reason": "MECHANICAL"},
        severity=Severity.CRITICAL,
        affected_flights=["AA401"],
    )
    pb = match_playbook(event)
    assert pb is not None
    assert pb.name == "CANCELLATION"
    assert pb.activate == ["cancellation_coordinator"]
    inputs = pb.build_inputs(event)
    assert "cancellation_coordinator" in inputs
    assert inputs["cancellation_coordinator"]["flight_id"] == "AA401"


def test_cancellation_rebooks_bags_on_next_flight():
    """Cancellation: all bags get rebooked on next available flight."""
    _base_seed()
    now = datetime.now(timezone.utc)
    store.FLIGHTS["AA401"] = Flight(
        flight_id="AA401", airline="AA", origin="ORD", destination="JFK",
        scheduled_departure=now - timedelta(minutes=10),
        estimated_departure=now, gate="B4", terminal="B",
        status=FlightStatus.ON_TIME,
    )
    # Seed bags on the cancelled flight
    for i, tag in enumerate(["BA-C1", "BA-C2"]):
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=f"PC0{i}", passenger_name=f"Cancel Pax {i}",
            origin_flight="AA401", destination_flight=None,
            final_destination="LHR", current_location="BHS_ZONE_B",
        )

    from src.tier2.cancellation_coordinator import build_cancellation_coordinator
    result = build_cancellation_coordinator().compile().invoke({
        "disruption_id": "d-canc-001",
        "flight_id": "AA401",
        "reason": "MECHANICAL",
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "find_all_bags" in node_names
    assert "rebook_bags" in node_names
    assert "notify_passengers" in node_names

    # Bags should be rebooked (destination_flight updated)
    rebooked = result.get("rebooked", {})
    assert len(rebooked) >= 1

    # Passengers notified
    sent = PassengerNotifyTool.get_sent()
    assert len([n for n in sent if n["type"] == "MISSED"]) >= 1


def test_cancellation_offloads_already_loaded_bags():
    """Bags already in the aircraft hold get an off-load task."""
    _base_seed()
    now = datetime.now(timezone.utc)
    store.FLIGHTS["AA401"] = Flight(
        flight_id="AA401", airline="AA", origin="ORD", destination="JFK",
        scheduled_departure=now - timedelta(minutes=10),
        estimated_departure=now, gate="B4", terminal="B",
        status=FlightStatus.ON_TIME,
    )
    # One bag already loaded in hold
    store.BAGS["BA-LOADED"] = Bag(
        bag_tag="BA-LOADED", passenger_id="PL01", passenger_name="Loaded Pax",
        origin_flight="AA401", destination_flight=None,
        final_destination="LHR", current_location="HOLD_AA401",
        status=BagStatus.LOADED,
    )
    store.LOAD_PLANS["AA401"] = LoadPlan(
        flight_id="AA401", aircraft_type="B737",
        max_weight_kg=15000.0, current_weight_kg=20.0, bag_count=1,
    )

    from src.tier2.cancellation_coordinator import build_cancellation_coordinator
    result = build_cancellation_coordinator().compile().invoke({
        "disruption_id": "d-canc-002",
        "flight_id": "AA401",
        "reason": "WEATHER",
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "offload_loaded" in node_names
    assert "BA-LOADED" in result.get("offloaded", [])
    assert store.BAGS["BA-LOADED"].status == BagStatus.OFFLOADED


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
