"""Phase 4 acceptance tests — Baggage Domain Coordinator (V2, deterministic).

No LLM mocking needed. All logic is Tier 1 (triage math) + Tier 2 (CP-SAT).
Same inputs always produce the same outputs.
"""
from datetime import datetime, timezone, timedelta

from src.tools import store
from src.tools.passenger_notify import PassengerNotifyTool
from src.models import (
    Bag, BagStatus, Flight, FlightStatus, LoadPlan,
    TransferConnection, CrewStatus,
)


# ── Seed helpers ──────────────────────────────────────────────────────────────

def _seed(departure_window: int = 25, crew_available: bool = True, available_crew: int = 4):
    """Seed with 5 Zone-B bags (move=8, recoverable) + 2 Zone-D bags (move=26, missed)."""
    store.reset()
    PassengerNotifyTool.clear()
    now = datetime.now(timezone.utc)

    store.FLIGHTS["AA401"] = Flight(
        flight_id="AA401", airline="AA", origin="ORD", destination="JFK",
        scheduled_departure=now - timedelta(minutes=32),
        estimated_departure=now,
        gate="B4", terminal="B", status=FlightStatus.DELAYED,
    )
    store.FLIGHTS["AA501"] = Flight(
        flight_id="AA501", airline="AA", origin="JFK", destination="LHR",
        scheduled_departure=now + timedelta(minutes=departure_window),
        estimated_departure=now + timedelta(minutes=departure_window),
        gate="B12", terminal="B",
    )

    # Zone B bags — move_time=8, slack = departure_window - 8
    for i, tag in enumerate(["BA-001", "BA-002", "BA-003", "BA-004", "BA-005"]):
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=f"P00{i+1}", passenger_name=f"Pax {i+1}",
            origin_flight="AA401", destination_flight="AA501",
            final_destination="LHR", current_location="BHS_ZONE_B",
        )
        store.CONNECTIONS[tag] = [TransferConnection(
            bag_tag=tag, passenger_id=f"P00{i+1}",
            inbound_flight="AA401", outbound_flight="AA501",
            connection_window_minutes=departure_window,
            minimum_connection_time=25,
            move_time_minutes=8,
            is_at_risk=True,
        )]

    # Zone D bags — move_time=26, slack = departure_window - 26
    for i, tag in enumerate(["BA-006", "BA-007"]):
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=f"P00{i+6}", passenger_name=f"Pax {i+6}",
            origin_flight="AA401", destination_flight="AA501",
            final_destination="LHR", current_location="BHS_ZONE_D",
        )
        store.CONNECTIONS[tag] = [TransferConnection(
            bag_tag=tag, passenger_id=f"P00{i+6}",
            inbound_flight="AA401", outbound_flight="AA501",
            connection_window_minutes=departure_window,
            minimum_connection_time=25,
            move_time_minutes=26,
            is_at_risk=True,
        )]

    store.LOAD_PLANS["AA501"] = LoadPlan(
        flight_id="AA501", aircraft_type="B737",
        max_weight_kg=15000.0, current_weight_kg=12000.0, bag_count=85,
    )
    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=available_crew, total_crew=6,
        active_tasks=2, can_take_exception=crew_available,
    )


# ── Triage unit tests (no graph needed) ──────────────────────────────────────

def test_prepare_context_finds_at_risk_bags():
    _seed()
    from src.tier2.baggage_coordinator import prepare_context
    result = prepare_context({"disruption_id": "d-001", "inbound_flight": "AA401",
                              "delay_minutes": 32})
    assert len(result["at_risk_connections"]) == 7
    assert set(result["at_risk_bag_tags"]) == {
        "BA-001", "BA-002", "BA-003", "BA-004", "BA-005", "BA-006", "BA-007"
    }
    assert result["outbound_flight"] == "AA501"


def test_fetch_departure_returns_window():
    _seed(departure_window=25)
    from src.tier2.baggage_coordinator import fetch_departure
    result = fetch_departure({"outbound_flight": "AA501"})
    assert 20 <= result["departure_window_minutes"] <= 30


def test_fetch_ramp_returns_availability():
    _seed(crew_available=True)
    from src.tier2.baggage_coordinator import fetch_ramp
    result = fetch_ramp({"inbound_flight": "AA401"})
    assert result["ramp_crew_available"] is True
    assert result["ramp_zone"] == "B"


# ── Full DAG integration tests (deterministic, no mocking) ───────────────────

def test_partial_scenario_deterministic():
    """25-min window: Zone B (move=8, slack=+17) saved; Zone D (move=26, slack=-1) missed."""
    _seed(departure_window=25)
    from src.tier2.baggage_coordinator import build_baggage_coordinator
    result = build_baggage_coordinator().compile().invoke({
        "disruption_id": "dis-001",
        "inbound_flight": "AA401",
        "delay_minutes": 32,
        "actions_taken": [],
    })

    assert result["feasibility_verdict"] == "PARTIAL"
    assert set(result["recoverable_bag_tags"]) == {"BA-001", "BA-002", "BA-003", "BA-004", "BA-005"}
    assert set(result["unrecoverable_bag_tags"]) == {"BA-006", "BA-007"}

    for tag in ["BA-001", "BA-002", "BA-003", "BA-004", "BA-005"]:
        assert store.BAGS[tag].status == BagStatus.CONFIRMED_LOADED
    for tag in ["BA-006", "BA-007"]:
        assert store.BAGS[tag].status == BagStatus.MISSED

    sent = PassengerNotifyTool.get_sent()
    at_risk = [n for n in sent if n["type"] == "AT_RISK"]
    missed = [n for n in sent if n["type"] == "MISSED"]
    recovered = [n for n in sent if n["type"] == "RECOVERED"]
    assert len(at_risk) == 5      # sent when exception routing opens
    assert len(missed) == 2       # sent for Zone D bags
    assert len(recovered) == 5    # sent after confirming scan

    # No LLM call — triage is deterministic
    node_names = [a["node"] for a in result["actions_taken"]]
    assert "triage_and_optimize" in node_names
    assert "close_loop" in node_names


def test_unrecoverable_when_window_too_short():
    """4-min window: all bags unrecoverable (even Zone B needs 8 min)."""
    _seed(departure_window=4)
    from src.tier2.baggage_coordinator import build_baggage_coordinator
    result = build_baggage_coordinator().compile().invoke({
        "disruption_id": "dis-002",
        "inbound_flight": "AA401",
        "delay_minutes": 32,
        "actions_taken": [],
    })

    assert result["feasibility_verdict"] == "UNRECOVERABLE"
    assert result["recoverable_bag_tags"] == []
    assert len(result["unrecoverable_bag_tags"]) == 7

    sent = PassengerNotifyTool.get_sent()
    assert all(n["type"] == "MISSED" for n in sent)


def test_all_recoverable_when_window_generous():
    """40-min window: all bags recoverable (Zone D needs 26, 40-26=+14 slack)."""
    _seed(departure_window=40)
    from src.tier2.baggage_coordinator import build_baggage_coordinator
    result = build_baggage_coordinator().compile().invoke({
        "disruption_id": "dis-003",
        "inbound_flight": "AA401",
        "delay_minutes": 10,
        "actions_taken": [],
    })

    assert result["feasibility_verdict"] == "RECOVERABLE"
    assert len(result["recoverable_bag_tags"]) == 7
    assert result["unrecoverable_bag_tags"] == []

    sent = PassengerNotifyTool.get_sent()
    # AT_RISK when routing opens; RECOVERED after confirming scan
    assert len([n for n in sent if n["type"] == "AT_RISK"]) == 7
    assert len([n for n in sent if n["type"] == "RECOVERED"]) == 7


def test_no_at_risk_bags_short_circuits():
    """When no bags are flagged at-risk, triage is skipped entirely."""
    store.reset()
    PassengerNotifyTool.clear()
    now = datetime.now(timezone.utc)
    store.FLIGHTS["AA403"] = Flight(
        flight_id="AA403", airline="AA", origin="MIA", destination="JFK",
        scheduled_departure=now - timedelta(minutes=5),
        estimated_departure=now,
        gate="C2", terminal="C", status=FlightStatus.DELAYED,
    )
    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=3, total_crew=5, active_tasks=0, can_take_exception=True
    )

    from src.tier2.baggage_coordinator import build_baggage_coordinator
    result = build_baggage_coordinator().compile().invoke({
        "disruption_id": "dis-004",
        "inbound_flight": "AA403",
        "delay_minutes": 5,
        "actions_taken": [],
    })

    assert result["feasibility_verdict"] == "RECOVERABLE"
    assert result["recoverable_bag_tags"] == []
    assert len(PassengerNotifyTool.get_sent()) == 0


def test_cpsat_invoked_under_crew_contention():
    """When recoverable bags > crew capacity, CP-SAT picks the optimal subset."""
    _seed(departure_window=25, available_crew=1)  # capacity = 1 crew × 3 = 3 bags
    from src.tier2.baggage_coordinator import build_baggage_coordinator
    result = build_baggage_coordinator().compile().invoke({
        "disruption_id": "dis-005",
        "inbound_flight": "AA401",
        "delay_minutes": 32,
        "actions_taken": [],
    })

    # 5 Zone-B bags recoverable by triage, but capacity = 1*3 = 3 → CP-SAT picks 3
    assert len(result["recoverable_bag_tags"]) == 3
    # 2 Zone-D (missed by triage) + 2 deferred by CP-SAT = 4 unrecoverable
    assert len(result["unrecoverable_bag_tags"]) == 4

    # Confirm CP-SAT was used
    triage_action = next(
        (a for a in result["actions_taken"] if a["node"] == "triage_and_optimize"), None
    )
    assert triage_action is not None
    assert "cpsat" in triage_action.get("tool", "")
