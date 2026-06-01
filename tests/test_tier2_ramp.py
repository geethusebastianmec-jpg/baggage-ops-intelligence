"""Phase 5 acceptance tests — Ramp, Dispatch, Comms coordinators."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from src.tools import store
from src.tools.passenger_notify import PassengerNotifyTool
from src.models import Flight, FlightStatus, LoadPlan, CrewStatus


def _seed_base():
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
        max_weight_kg=15000.0, current_weight_kg=12000.0,
        bag_count=85, pending_bags=["BA-001", "BA-002"],
    )
    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=3, total_crew=5,
        active_tasks=2, can_take_exception=True,
    )


# ── Ramp Coordinator ─────────────────────────────────────────────────────────

def test_ramp_assigns_when_crew_available():
    _seed_base()
    from src.tier2.ramp_coordinator import build_ramp_coordinator
    graph = build_ramp_coordinator().compile()
    result = graph.invoke({
        "disruption_id": "d-001",
        "bag_tags": ["BA-001", "BA-002"],
        "from_flight": "AA401",
        "to_flight": "AA501",
        "zone": "B",
        "actions_taken": [],
    })
    assert result["task_ticket"] is not None
    assert result.get("error") is None
    # Crew consumed
    assert store.CREW_STATUS["B"].active_tasks == 3


def test_ramp_escalates_when_no_crew():
    _seed_base()
    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=0, total_crew=5,
        active_tasks=5, can_take_exception=False,
    )
    from src.tier2.ramp_coordinator import build_ramp_coordinator
    graph = build_ramp_coordinator().compile()
    result = graph.invoke({
        "disruption_id": "d-002",
        "bag_tags": ["BA-001"],
        "from_flight": "AA401",
        "to_flight": "AA501",
        "zone": "B",
        "actions_taken": [],
    })
    assert result["task_ticket"] is None
    node_names = [a["node"] for a in result["actions_taken"]]
    assert "escalate" in node_names


# ── Dispatch Coordinator ─────────────────────────────────────────────────────

def test_dispatch_holds_when_many_bags_recoverable():
    """20 recoverable bags: 20 × $150 = $3,000 > 5-min hold × $500 = $2,500 → HOLD."""
    _seed_base()
    from src.tier2.dispatch_coordinator import build_dispatch_coordinator
    graph = build_dispatch_coordinator().compile()
    result = graph.invoke({
        "disruption_id": "d-003",
        "flight_id": "AA501",
        "recoverable_bag_count": 20,
        "actions_taken": [],
    })
    assert result["hold_decision"] == "HOLD"


def test_dispatch_departs_when_few_bags_not_worth_holding():
    """3 recoverable bags: 3 × $150 = $450 < 5-min hold × $500 = $2,500 → DEPART."""
    _seed_base()
    from src.tier2.dispatch_coordinator import build_dispatch_coordinator
    graph = build_dispatch_coordinator().compile()
    result = graph.invoke({
        "disruption_id": "d-003b",
        "flight_id": "AA501",
        "recoverable_bag_count": 3,
        "actions_taken": [],
    })
    assert result["hold_decision"] == "DEPART"


def test_dispatch_departs_when_window_too_short():
    """5-min window → DEPART regardless of pending bags."""
    store.reset()
    now = datetime.now(timezone.utc)
    store.FLIGHTS["AA501"] = Flight(
        flight_id="AA501", airline="AA", origin="JFK", destination="LHR",
        scheduled_departure=now + timedelta(minutes=4),
        estimated_departure=now + timedelta(minutes=4),
        gate="B12", terminal="B",
    )
    store.LOAD_PLANS["AA501"] = LoadPlan(
        flight_id="AA501", aircraft_type="B737",
        max_weight_kg=15000.0, current_weight_kg=12000.0, bag_count=85,
    )
    from src.tier2.dispatch_coordinator import build_dispatch_coordinator
    graph = build_dispatch_coordinator().compile()
    result = graph.invoke({
        "disruption_id": "d-004",
        "flight_id": "AA501",
        "recoverable_bag_count": 5,
        "actions_taken": [],
    })
    assert result["hold_decision"] == "DEPART"


def test_dispatch_departs_when_no_bags():
    """No recoverable bags → DEPART."""
    _seed_base()
    store.LOAD_PLANS["AA501"] = LoadPlan(
        flight_id="AA501", aircraft_type="B737",
        max_weight_kg=15000.0, current_weight_kg=12000.0, bag_count=85,
    )
    from src.tier2.dispatch_coordinator import build_dispatch_coordinator
    graph = build_dispatch_coordinator().compile()
    result = graph.invoke({
        "disruption_id": "d-005",
        "flight_id": "AA501",
        "recoverable_bag_count": 0,
        "actions_taken": [],
    })
    assert result["hold_decision"] == "DEPART"


# ── Comms Coordinator ────────────────────────────────────────────────────────

def test_comms_sends_missed_notifications():
    PassengerNotifyTool.clear()
    from src.tier2.comms_coordinator import build_comms_coordinator
    graph = build_comms_coordinator().compile()
    result = graph.invoke({
        "disruption_id": "d-006",
        "notifications": [
            {"passenger_id": "P001", "bag_tag": "BA-001", "type": "MISSED"},
            {"passenger_id": "P002", "bag_tag": "BA-002", "type": "MISSED"},
        ],
        "actions_taken": [],
    })
    assert result["sent_count"] == 2
    assert result["failed_count"] == 0
    sent = PassengerNotifyTool.get_sent()
    assert len(sent) == 2
    assert all(n["type"] == "MISSED" for n in sent)


def test_comms_sends_at_risk_notifications():
    PassengerNotifyTool.clear()
    from src.tier2.comms_coordinator import build_comms_coordinator
    graph = build_comms_coordinator().compile()
    result = graph.invoke({
        "disruption_id": "d-007",
        "notifications": [
            {"passenger_id": "P003", "bag_tag": "BA-003", "type": "AT_RISK", "outbound_flight": "AA501"},
        ],
        "actions_taken": [],
    })
    assert result["sent_count"] == 1
    sent = PassengerNotifyTool.get_sent()
    assert sent[0]["type"] == "AT_RISK"


def test_comms_empty_notifications():
    PassengerNotifyTool.clear()
    from src.tier2.comms_coordinator import build_comms_coordinator
    graph = build_comms_coordinator().compile()
    result = graph.invoke({"disruption_id": "d-008", "notifications": [], "actions_taken": []})
    assert result["sent_count"] == 0
    assert result["failed_count"] == 0
