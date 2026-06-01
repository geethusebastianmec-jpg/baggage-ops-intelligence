"""JFK Hub Crisis — seed data for the demo scenario.

Populates the in-memory tool store with:
  - 5 flights (3 delayed inbounds, 2 on-time outbounds)
  - 40 bags total, 12 with active connections
  - Ramp crew state across two zones

Expected demo outcome:
  AA401 (ORD→JFK, +32 min) → 7 bags → AA501 (JFK→LHR, departs in 25 min)
    → 5 recoverable (exception routing), 2 truly missed
  AA402 (LAX→JFK, +18 min) → 3 bags → AA501 (JFK→LHR)
    → 3 recoverable (within window with exception routing)
  AA403 (MIA→JFK, +11 min) → 2 bags → AA502 (JFK→CDG, departs in 40 min)
    → 2 no-action-needed (sufficient window remaining)
  Remaining 28 bags → no connections, all fine
"""
from datetime import datetime, timezone, timedelta

from src.tools import store
from src.models import (
    Bag, BagStatus, Flight, FlightStatus, LoadPlan, TransferConnection, CrewStatus,
)
from src.solver.rerouter import FlightLeg


def load(now: datetime | None = None) -> None:
    """Load all seed data into the in-memory store. Call before running the scenario."""
    store.reset()
    if now is None:
        now = datetime.now(timezone.utc)

    # ── Flights ───────────────────────────────────────────────────────────────

    store.FLIGHTS["AA401"] = Flight(
        flight_id="AA401", airline="AA", origin="ORD", destination="JFK",
        scheduled_departure=now - timedelta(minutes=32),
        estimated_departure=now,
        gate="B4", terminal="B", status=FlightStatus.DELAYED,
    )
    store.FLIGHTS["AA402"] = Flight(
        flight_id="AA402", airline="AA", origin="LAX", destination="JFK",
        scheduled_departure=now - timedelta(minutes=18),
        estimated_departure=now + timedelta(minutes=2),
        gate="B7", terminal="B", status=FlightStatus.DELAYED,
    )
    store.FLIGHTS["AA403"] = Flight(
        flight_id="AA403", airline="AA", origin="MIA", destination="JFK",
        scheduled_departure=now - timedelta(minutes=11),
        estimated_departure=now + timedelta(minutes=4),
        gate="C2", terminal="C", status=FlightStatus.DELAYED,
    )
    store.FLIGHTS["AA501"] = Flight(
        flight_id="AA501", airline="AA", origin="JFK", destination="LHR",
        scheduled_departure=now + timedelta(minutes=25),
        estimated_departure=now + timedelta(minutes=25),
        gate="B12", terminal="B", status=FlightStatus.ON_TIME,
    )
    store.FLIGHTS["AA502"] = Flight(
        flight_id="AA502", airline="AA", origin="JFK", destination="CDG",
        scheduled_departure=now + timedelta(minutes=40),
        estimated_departure=now + timedelta(minutes=40),
        gate="C8", terminal="C", status=FlightStatus.ON_TIME,
    )

    # ── Rerouting flights (for MIP layer — bags that miss their connection) ──────
    # These are flights that missed bags can be put on.
    # The MIP rerouter (Tier 2b) assigns bags to these flights optimally.

    store.REROUTING_FLIGHTS.extend([
        FlightLeg("AA503", "JFK", "LHR", departs_in_minutes=120,  remaining_capacity=15),
        FlightLeg("AA601", "JFK", "LHR", departs_in_minutes=480,  remaining_capacity=30),
        FlightLeg("AA504", "JFK", "CDG", departs_in_minutes=240,  remaining_capacity=12),
        FlightLeg("AA602", "JFK", "CDG", departs_in_minutes=720,  remaining_capacity=25),
        FlightLeg("AA701", "JFK", "LHR", departs_in_minutes=1440, remaining_capacity=50),
    ])

    # ── Load plans ────────────────────────────────────────────────────────────

    store.LOAD_PLANS["AA501"] = LoadPlan(
        flight_id="AA501", aircraft_type="B737",
        max_weight_kg=15000.0, current_weight_kg=11600.0, bag_count=80,
    )
    store.LOAD_PLANS["AA502"] = LoadPlan(
        flight_id="AA502", aircraft_type="B767",
        max_weight_kg=20000.0, current_weight_kg=14000.0, bag_count=95,
    )

    # ── Ramp crew ─────────────────────────────────────────────────────────────

    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=4, total_crew=6,
        active_tasks=2, can_take_exception=True,
    )
    store.CREW_STATUS["C"] = CrewStatus(
        zone="C", available_crew=3, total_crew=4,
        active_tasks=1, can_take_exception=True,
    )

    # ── Bags: AA401 → AA501 (7 bags, all at risk) ─────────────────────────────
    # Departure window for AA501: 25 min from now.
    # BA-001..005 are in Zone B (near gate): move_time=8, slack = 25-8 = +17 → RECOVERABLE
    # BA-006..007 are in Zone D (deep queue):  move_time=26, slack = 25-26 = -1 → UNRECOVERABLE
    # Outcome is determined by deterministic triage, not an LLM.

    aa401_bags_zone_b = [
        ("BA-001", "P101", "Emma Wilson"),
        ("BA-002", "P102", "James Chen"),
        ("BA-003", "P103", "Sofia Martinez"),
        ("BA-004", "P104", "Oliver Brown"),
        ("BA-005", "P105", "Isabella Johnson"),
    ]
    for tag, pid, name in aa401_bags_zone_b:
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=pid, passenger_name=name,
            origin_flight="AA401", destination_flight="AA501",
            final_destination="LHR", current_location="BHS_ZONE_B",
            weight_kg=22.0,
        )
        store.CONNECTIONS[tag] = [TransferConnection(
            bag_tag=tag, passenger_id=pid,
            inbound_flight="AA401", outbound_flight="AA501",
            connection_window_minutes=25,
            minimum_connection_time=25,
            move_time_minutes=8,       # Zone B — near gate, 8-min sprint
            is_at_risk=True,
            risk_reason="AA401 delayed 32 min",
        )]

    aa401_bags_zone_d = [
        ("BA-006", "P106", "Noah Davis"),
        ("BA-007", "P107", "Mia Thompson"),
    ]
    for tag, pid, name in aa401_bags_zone_d:
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=pid, passenger_name=name,
            origin_flight="AA401", destination_flight="AA501",
            final_destination="LHR", current_location="BHS_ZONE_D",
            weight_kg=22.0,
        )
        store.CONNECTIONS[tag] = [TransferConnection(
            bag_tag=tag, passenger_id=pid,
            inbound_flight="AA401", outbound_flight="AA501",
            connection_window_minutes=25,
            minimum_connection_time=25,
            move_time_minutes=26,      # Zone D — deep BHS queue, 26-min tug run
            is_at_risk=True,
            risk_reason="AA401 delayed 32 min — Zone D bags physically impossible",
        )]

    # ── Bags: AA402 → AA501 (3 bags, at risk but recoverable) ─────────────────
    # Window: 25 min. Zone B bags: move_time=8, slack=+17 → RECOVERABLE

    aa402_bags = [
        ("BA-008", "P201", "Liam Anderson"),
        ("BA-009", "P202", "Ava Thomas"),
        ("BA-010", "P203", "Ethan Jackson"),
    ]
    for tag, pid, name in aa402_bags:
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=pid, passenger_name=name,
            origin_flight="AA402", destination_flight="AA501",
            final_destination="LHR", current_location="BHS_ZONE_B",
            weight_kg=19.0,
        )
        store.CONNECTIONS[tag] = [TransferConnection(
            bag_tag=tag, passenger_id=pid,
            inbound_flight="AA402", outbound_flight="AA501",
            connection_window_minutes=25,
            minimum_connection_time=25,
            move_time_minutes=8,       # Zone B — recoverable
            is_at_risk=True,
            risk_reason="AA402 delayed 18 min",
        )]

    # ── Bags: AA403 → AA502 (2 bags, NOT at risk — sufficient window) ──────────
    # Window: 40 min. Zone C bags: move_time=10, slack=+30 → comfortable, not flagged

    aa403_bags = [
        ("BA-011", "P301", "Charlotte Harris"),
        ("BA-012", "P302", "Benjamin Lee"),
    ]
    for tag, pid, name in aa403_bags:
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=pid, passenger_name=name,
            origin_flight="AA403", destination_flight="AA502",
            final_destination="CDG", current_location="BHS_ZONE_C",
            weight_kg=18.0,
        )
        store.CONNECTIONS[tag] = [TransferConnection(
            bag_tag=tag, passenger_id=pid,
            inbound_flight="AA403", outbound_flight="AA502",
            connection_window_minutes=40,
            minimum_connection_time=25,
            move_time_minutes=10,      # Zone C — comfortable
            is_at_risk=False,
        )]

    # ── 28 non-connecting bags on various flights ──────────────────────────────
    for i in range(28):
        tag = f"BX-{i+1:03d}"
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=f"PX{i+1:03d}",
            passenger_name=f"Passenger {i+1}",
            origin_flight="AA401" if i < 14 else "AA402",
            final_destination="JFK",
            current_location="CAROUSEL_3",
            status=BagStatus.DELIVERED,
        )
