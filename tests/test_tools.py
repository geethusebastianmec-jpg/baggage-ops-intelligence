"""Phase 3 acceptance tests — Tier 3 mock tool layer."""
import pytest
from datetime import datetime, timezone, timedelta

from src.tools import store
from src.tools.bhs import BHSTool
from src.tools.load_plan import LoadPlanTool
from src.tools.ramp import RampTool
from src.tools.passenger_notify import PassengerNotifyTool
from src.tools.aodb import AODBTool
from src.models import (
    Bag, BagStatus, Flight, FlightStatus, LoadPlan, TransferConnection, CrewStatus,
)


def _seed():
    """Minimal seed data for tool tests."""
    store.reset()
    now = datetime.now(timezone.utc)

    store.FLIGHTS["AA401"] = Flight(
        flight_id="AA401", airline="AA", origin="ORD", destination="JFK",
        scheduled_departure=now - timedelta(minutes=32),
        estimated_departure=now,
        gate="B4", terminal="B", status=FlightStatus.DELAYED,
    )
    store.FLIGHTS["AA501"] = Flight(
        flight_id="AA501", airline="AA", origin="JFK", destination="LHR",
        scheduled_departure=now + timedelta(minutes=25),
        estimated_departure=now + timedelta(minutes=25),
        gate="B12", terminal="B",
    )

    store.BAGS["BA-001"] = Bag(
        bag_tag="BA-001", passenger_id="P001", passenger_name="Alice",
        origin_flight="AA401", destination_flight="AA501",
        final_destination="LHR", current_location="BHS_ZONE_B",
    )
    store.BAGS["BA-002"] = Bag(
        bag_tag="BA-002", passenger_id="P002", passenger_name="Bob",
        origin_flight="AA401", destination_flight="AA501",
        final_destination="LHR", current_location="BHS_ZONE_B",
    )

    store.CONNECTIONS["BA-001"] = [TransferConnection(
        bag_tag="BA-001", passenger_id="P001",
        inbound_flight="AA401", outbound_flight="AA501",
        connection_window_minutes=5, minimum_connection_time=25, is_at_risk=True,
        risk_reason="Inbound delayed 32 min",
    )]
    store.CONNECTIONS["BA-002"] = [TransferConnection(
        bag_tag="BA-002", passenger_id="P002",
        inbound_flight="AA401", outbound_flight="AA501",
        connection_window_minutes=5, minimum_connection_time=25, is_at_risk=True,
        risk_reason="Inbound delayed 32 min",
    )]

    store.LOAD_PLANS["AA501"] = LoadPlan(
        flight_id="AA501", aircraft_type="B737",
        max_weight_kg=15000.0, current_weight_kg=12000.0, bag_count=85,
    )

    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=3, total_crew=5,
        active_tasks=2, can_take_exception=True,
    )


# ── BHS tests ─────────────────────────────────────────────────────────────────

def test_bhs_query_bag():
    _seed()
    tool = BHSTool()
    bag = tool.query_bag("BA-001")
    assert bag is not None
    assert bag.passenger_name == "Alice"


def test_bhs_query_missing_bag():
    _seed()
    tool = BHSTool()
    assert tool.query_bag("NONEXISTENT") is None


def test_bhs_query_transfer_risks():
    _seed()
    tool = BHSTool()
    risks = tool.query_transfer_risks("AA401")
    assert len(risks) == 2
    assert all(r.outbound_flight == "AA501" for r in risks)


def test_bhs_open_exception_routing():
    _seed()
    tool = BHSTool()
    ticket = tool.open_exception_routing(["BA-001", "BA-002"], "Transfer at risk", "d-001", "dis-001")
    assert ticket.ticket_id
    assert set(ticket.bag_tags) == {"BA-001", "BA-002"}
    # Bags should now be in EXCEPTION status
    assert store.BAGS["BA-001"].status == BagStatus.EXCEPTION
    assert store.BAGS["BA-002"].status == BagStatus.EXCEPTION


def test_bhs_mark_missed():
    _seed()
    tool = BHSTool()
    result = tool.mark_bag_missed("BA-001")
    assert result is True
    assert store.BAGS["BA-001"].status == BagStatus.MISSED


# ── Load plan tests ───────────────────────────────────────────────────────────

def test_load_plan_get():
    _seed()
    tool = LoadPlanTool()
    lp = tool.get_load_plan("AA501")
    assert lp is not None
    assert lp.bag_count == 85
    assert lp.available_weight_kg == 3000.0


def test_load_plan_add_pending_bags():
    _seed()
    tool = LoadPlanTool()
    updated = tool.add_pending_bags("AA501", ["BA-001", "BA-002"])
    assert updated is not None
    assert "BA-001" in updated.pending_bags
    assert "BA-002" in updated.pending_bags


def test_load_plan_remove_bags():
    _seed()
    tool = LoadPlanTool()
    updated = tool.remove_bags("AA501", ["BA-001"], weight_kg_per_bag=20.0)
    assert updated is not None
    assert updated.bag_count == 84
    assert updated.current_weight_kg == 11980.0


# ── Ramp tests ────────────────────────────────────────────────────────────────

def test_ramp_get_crew():
    _seed()
    tool = RampTool()
    crew = tool.get_crew_availability("B")
    assert crew is not None
    assert crew.can_take_exception is True
    assert crew.available_crew == 3


def test_ramp_assign_task():
    _seed()
    tool = RampTool()
    ticket = tool.assign_exception_task(["BA-001"], "AA401", "AA501", "B")
    assert ticket is not None
    assert ticket.task_type == "EXCEPTION_TRANSFER"
    # Crew capacity reduced
    assert store.CREW_STATUS["B"].active_tasks == 3
    assert store.CREW_STATUS["B"].available_crew == 2


def test_ramp_no_crew_available():
    _seed()
    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=0, total_crew=5, active_tasks=5, can_take_exception=False
    )
    tool = RampTool()
    ticket = tool.assign_exception_task(["BA-001"], "AA401", "AA501", "B")
    assert ticket is None


# ── Passenger notify tests ────────────────────────────────────────────────────

def test_notify_at_risk():
    PassengerNotifyTool.clear()
    tool = PassengerNotifyTool()
    result = tool.notify_bag_at_risk("P001", "BA-001", "AA501")
    assert result is True
    sent = PassengerNotifyTool.get_sent()
    assert len(sent) == 1
    assert sent[0]["type"] == "AT_RISK"
    assert "BA-001" in sent[0]["message"]


def test_notify_missed():
    PassengerNotifyTool.clear()
    tool = PassengerNotifyTool()
    result = tool.notify_bag_missed("P002", "BA-002")
    assert result is True
    assert PassengerNotifyTool.get_sent()[0]["type"] == "MISSED"


# ── AODB tests ────────────────────────────────────────────────────────────────

def test_aodb_get_flight():
    _seed()
    tool = AODBTool()
    flight = tool.get_flight("AA401")
    assert flight is not None
    assert flight.status == FlightStatus.DELAYED


def test_aodb_departure_window():
    _seed()
    tool = AODBTool()
    window = tool.get_departure_window_minutes("AA501")
    # Should be ~25 min (seed sets departure 25 min from now)
    assert 20 <= window <= 30


def test_aodb_apply_delay():
    _seed()
    tool = AODBTool()
    updated = tool.apply_delay("AA501", 10)
    assert updated is not None
    assert updated.status == FlightStatus.DELAYED
    new_window = tool.get_departure_window_minutes("AA501")
    assert new_window >= 30  # was 25, now 35+


def test_action_log_populated():
    _seed()
    PassengerNotifyTool.clear()
    store.ACTION_LOG.clear()
    bhs = BHSTool()
    bhs.open_exception_routing(["BA-001"], "test", "d-001", "dis-001")
    assert len(store.ACTION_LOG) >= 1
    assert store.ACTION_LOG[-1]["tool"] == "bhs"
