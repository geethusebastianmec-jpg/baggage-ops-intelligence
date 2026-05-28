"""Phase 4 acceptance tests — Baggage Domain Coordinator.

LLM call is mocked so tests run without an API key.
"""
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from src.tools import store
from src.tools.passenger_notify import PassengerNotifyTool
from src.models import (
    Bag, BagStatus, Flight, FlightStatus, LoadPlan,
    TransferConnection, CrewStatus,
)


# ── Seed helpers ──────────────────────────────────────────────────────────────

def _seed_scenario(delay_minutes: int = 32, departure_window: int = 25, crew_available: bool = True):
    """Seed a hub scenario: AA401 (delayed inbound) → AA501 (outbound)."""
    store.reset()
    PassengerNotifyTool.clear()
    now = datetime.now(timezone.utc)

    store.FLIGHTS["AA401"] = Flight(
        flight_id="AA401", airline="AA", origin="ORD", destination="JFK",
        scheduled_departure=now - timedelta(minutes=delay_minutes),
        estimated_departure=now,
        gate="B4", terminal="B", status=FlightStatus.DELAYED,
    )
    store.FLIGHTS["AA501"] = Flight(
        flight_id="AA501", airline="AA", origin="JFK", destination="LHR",
        scheduled_departure=now + timedelta(minutes=departure_window),
        estimated_departure=now + timedelta(minutes=departure_window),
        gate="B12", terminal="B",
    )

    # Remaining window after delay. Coordinator is always invoked with at-risk bags,
    # so we always set is_at_risk=True; the LLM decides if they're recoverable.
    remaining_window = max(0, departure_window - delay_minutes)
    for i, (tag, name) in enumerate([("BA-001", "Alice"), ("BA-002", "Bob"), ("BA-003", "Carol")]):
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=f"P00{i+1}", passenger_name=name,
            origin_flight="AA401", destination_flight="AA501",
            final_destination="LHR", current_location="BHS_ZONE_B",
        )
        store.CONNECTIONS[tag] = [TransferConnection(
            bag_tag=tag, passenger_id=f"P00{i+1}",
            inbound_flight="AA401", outbound_flight="AA501",
            connection_window_minutes=remaining_window,
            minimum_connection_time=25,
            is_at_risk=True,
            risk_reason="Inbound delayed — flagged by Tier 1",
        )]

    store.LOAD_PLANS["AA501"] = LoadPlan(
        flight_id="AA501", aircraft_type="B737",
        max_weight_kg=15000.0, current_weight_kg=12000.0, bag_count=85,
    )
    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=3 if crew_available else 0,
        total_crew=5, active_tasks=2,
        can_take_exception=crew_available,
    )


def _mock_llm_response(verdict: str, recoverable: list[str], unrecoverable: list[str], reasoning: str):
    """Build a mock ChatAnthropic response returning the given JSON."""
    response_json = json.dumps({
        "verdict": verdict,
        "recoverable_bags": recoverable,
        "unrecoverable_bags": unrecoverable,
        "reasoning": reasoning,
    })
    mock_response = MagicMock()
    mock_response.content = response_json
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response
    return mock_llm


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_prepare_context_finds_at_risk_bags():
    """prepare_context correctly identifies all at-risk connections."""
    _seed_scenario()
    from src.tier2.baggage_coordinator import prepare_context
    result = prepare_context({"disruption_id": "d-001", "inbound_flight": "AA401", "delay_minutes": 32})
    assert len(result["at_risk_connections"]) == 3
    assert set(result["at_risk_bag_tags"]) == {"BA-001", "BA-002", "BA-003"}
    assert result["outbound_flight"] == "AA501"


def test_fetch_departure_returns_window():
    _seed_scenario(departure_window=25)
    from src.tier2.baggage_coordinator import fetch_departure
    result = fetch_departure({"outbound_flight": "AA501"})
    assert 20 <= result["departure_window_minutes"] <= 30


def test_fetch_ramp_returns_availability():
    _seed_scenario(crew_available=True)
    from src.tier2.baggage_coordinator import fetch_ramp
    result = fetch_ramp({"inbound_flight": "AA401"})
    assert result["ramp_crew_available"] is True
    assert result["ramp_zone"] == "B"


@patch("src.tier2.baggage_coordinator.ChatAnthropic")
def test_full_recoverable_scenario(mock_anthropic_cls):
    """All 3 bags recoverable: exception routing opened, ramp task assigned."""
    _seed_scenario(delay_minutes=10, departure_window=40)
    mock_anthropic_cls.return_value = _mock_llm_response(
        "RECOVERABLE", ["BA-001", "BA-002", "BA-003"], [],
        "Departure window comfortable, crew available.",
    )

    from src.tier2.baggage_coordinator import baggage_coordinator, build_baggage_coordinator
    graph = build_baggage_coordinator().compile()

    result = graph.invoke({
        "disruption_id": "dis-001",
        "inbound_flight": "AA401",
        "delay_minutes": 10,
        "actions_taken": [],
    })

    assert result["feasibility_verdict"] == "RECOVERABLE"
    assert set(result["recoverable_bag_tags"]) == {"BA-001", "BA-002", "BA-003"}
    assert result["unrecoverable_bag_tags"] == []

    # All bags should be in EXCEPTION (exception routing opened)
    for tag in ["BA-001", "BA-002", "BA-003"]:
        assert store.BAGS[tag].status == BagStatus.EXCEPTION

    # Load plan should have pending bags
    lp = store.LOAD_PLANS["AA501"]
    assert "BA-001" in lp.pending_bags

    # No passenger notifications (bags are being saved)
    assert len(PassengerNotifyTool.get_sent()) == 0

    # Actions log has entries from all nodes
    actions = result["actions_taken"]
    node_names = [a["node"] for a in actions]
    assert "prepare_context" in node_names
    assert "route_bags" in node_names


@patch("src.tier2.baggage_coordinator.ChatAnthropic")
def test_full_unrecoverable_scenario(mock_anthropic_cls):
    """All 3 bags missed: marked MISSED, passengers notified."""
    _seed_scenario(delay_minutes=45, departure_window=5)
    mock_anthropic_cls.return_value = _mock_llm_response(
        "UNRECOVERABLE", [], ["BA-001", "BA-002", "BA-003"],
        "Departure window only 5 min — impossible to transfer.",
    )

    from src.tier2.baggage_coordinator import build_baggage_coordinator
    graph = build_baggage_coordinator().compile()

    result = graph.invoke({
        "disruption_id": "dis-002",
        "inbound_flight": "AA401",
        "delay_minutes": 45,
        "actions_taken": [],
    })

    assert result["feasibility_verdict"] == "UNRECOVERABLE"
    assert result["recoverable_bag_tags"] == []
    assert set(result["unrecoverable_bag_tags"]) == {"BA-001", "BA-002", "BA-003"}

    # All bags should be MISSED
    for tag in ["BA-001", "BA-002", "BA-003"]:
        assert store.BAGS[tag].status == BagStatus.MISSED

    # 3 passenger notifications sent
    sent = PassengerNotifyTool.get_sent()
    assert len(sent) == 3
    assert all(n["type"] == "MISSED" for n in sent)


@patch("src.tier2.baggage_coordinator.ChatAnthropic")
def test_partial_scenario(mock_anthropic_cls):
    """2 bags recoverable, 1 missed — both route_bags and flag_missed execute."""
    _seed_scenario(delay_minutes=30, departure_window=30)
    mock_anthropic_cls.return_value = _mock_llm_response(
        "PARTIAL", ["BA-001", "BA-002"], ["BA-003"],
        "BA-001 and BA-002 reachable via exception routing; BA-003 too far in BHS zone.",
    )

    from src.tier2.baggage_coordinator import build_baggage_coordinator
    graph = build_baggage_coordinator().compile()

    result = graph.invoke({
        "disruption_id": "dis-003",
        "inbound_flight": "AA401",
        "delay_minutes": 30,
        "actions_taken": [],
    })

    assert result["feasibility_verdict"] == "PARTIAL"
    assert set(result["recoverable_bag_tags"]) == {"BA-001", "BA-002"}
    assert result["unrecoverable_bag_tags"] == ["BA-003"]

    assert store.BAGS["BA-001"].status == BagStatus.EXCEPTION
    assert store.BAGS["BA-002"].status == BagStatus.EXCEPTION
    assert store.BAGS["BA-003"].status == BagStatus.MISSED

    sent = PassengerNotifyTool.get_sent()
    assert len(sent) == 1
    assert sent[0]["bag_tag"] == "BA-003"


@patch("src.tier2.baggage_coordinator.ChatAnthropic")
def test_no_at_risk_bags_short_circuits(mock_anthropic_cls):
    """When no bags are at risk, LLM is NOT called and graph exits cleanly."""
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
    graph = build_baggage_coordinator().compile()

    result = graph.invoke({
        "disruption_id": "dis-004",
        "inbound_flight": "AA403",
        "delay_minutes": 5,
        "actions_taken": [],
    })

    # LLM not invoked since no at-risk bags
    mock_anthropic_cls.assert_not_called()
    assert result["feasibility_verdict"] == "RECOVERABLE"
    assert result["recoverable_bag_tags"] == []
