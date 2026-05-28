"""Phase 2 acceptance tests — domain data models."""
import json
from datetime import datetime, timedelta
from src.models import (
    Flight, FlightStatus, DelayEvent, DelayReason,
    Bag, BagStatus, TransferConnection, LoadPlan,
    DisruptionEvent, DisruptionType, Severity,
    AgentDecision, ActionRecord, FeasibilityVerdict, FeasibilityResult,
    CrewStatus,
)


# ── Flight models ─────────────────────────────────────────────────────────────

def test_flight_delay_minutes():
    now = datetime(2025, 1, 1, 12, 0)
    f = Flight(
        flight_id="AA401",
        airline="AA",
        origin="ORD",
        destination="JFK",
        scheduled_departure=now,
        estimated_departure=now + timedelta(minutes=32),
        gate="B12",
        terminal="B",
    )
    assert f.delay_minutes == 32
    assert f.status == FlightStatus.ON_TIME


def test_delay_event_defaults():
    e = DelayEvent(flight_id="AA401", delay_minutes=32)
    assert e.event_id
    assert e.source == "ACARS"
    assert e.reason == DelayReason.UNKNOWN
    assert isinstance(e.detected_at, datetime)


def test_flight_roundtrip_json():
    now = datetime(2025, 1, 1, 12, 0)
    f = Flight(
        flight_id="AA401", airline="AA", origin="ORD", destination="JFK",
        scheduled_departure=now, estimated_departure=now, gate="B12", terminal="B",
    )
    assert Flight.model_validate_json(f.model_dump_json()).flight_id == "AA401"


# ── Bag models ────────────────────────────────────────────────────────────────

def test_transfer_connection_slack():
    tc = TransferConnection(
        bag_tag="0074123456",
        passenger_id="P001",
        inbound_flight="AA401",
        outbound_flight="AA501",
        connection_window_minutes=15,
        minimum_connection_time=30,
    )
    assert tc.slack_minutes == -15
    assert tc.is_breached is True
    assert tc.is_at_risk is False  # not yet flagged, just computed


def test_transfer_connection_safe():
    tc = TransferConnection(
        bag_tag="0074123457",
        passenger_id="P002",
        inbound_flight="AA403",
        outbound_flight="AA502",
        connection_window_minutes=40,
        minimum_connection_time=25,
    )
    assert tc.slack_minutes == 15
    assert tc.is_breached is False


def test_load_plan_available_weight():
    lp = LoadPlan(
        flight_id="AA501",
        aircraft_type="B737",
        max_weight_kg=15000.0,
        current_weight_kg=12000.0,
        bag_count=85,
    )
    assert lp.available_weight_kg == 3000.0


def test_bag_roundtrip_json():
    bag = Bag(
        bag_tag="0074123456",
        passenger_id="P001",
        passenger_name="John Doe",
        origin_flight="AA401",
        destination_flight="AA501",
        final_destination="LHR",
        current_location="BHS_ZONE_B",
    )
    assert Bag.model_validate_json(bag.model_dump_json()).bag_tag == "0074123456"


# ── Event models ──────────────────────────────────────────────────────────────

def test_disruption_event_defaults():
    e = DisruptionEvent(
        event_type=DisruptionType.FLIGHT_DELAY,
        payload={"flight_id": "AA401", "delay_minutes": 32},
        affected_flights=["AA401"],
    )
    assert e.event_id
    assert e.severity == Severity.MEDIUM
    assert isinstance(e.created_at, datetime)


def test_action_record_roundtrip():
    ar = ActionRecord(
        decision_id="d-001",
        disruption_id="dis-001",
        agent="baggage_coordinator",
        tool="bhs",
        input={"bag_tag": "0074123456"},
        output={"status": "EXCEPTION_OPENED"},
        success=True,
        duration_ms=150,
    )
    data = json.loads(ar.model_dump_json())
    assert data["tool"] == "bhs"
    assert data["success"] is True


def test_crew_status_utilization():
    cs = CrewStatus(zone="B", available_crew=3, total_crew=5, active_tasks=4, can_take_exception=True)
    assert cs.utilization == 0.8


def test_feasibility_result():
    fr = FeasibilityResult(
        verdict=FeasibilityVerdict.PARTIAL,
        recoverable_bags=["BA001", "BA002"],
        unrecoverable_bags=["BA003"],
        reasoning="Window too tight for BA003",
        recommended_actions=["Open exception routing for BA001, BA002", "Notify passenger on BA003"],
    )
    assert len(fr.recoverable_bags) == 2
    assert fr.verdict == FeasibilityVerdict.PARTIAL
