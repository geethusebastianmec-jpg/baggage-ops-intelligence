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
    # Connection window: ~25 min outbound - 32 min delay = window breached
    # Ramp can recover 5 quickly; 2 are too far in BHS queue

    aa401_bags = [
        ("BA-001", "P101", "Emma Wilson"),
        ("BA-002", "P102", "James Chen"),
        ("BA-003", "P103", "Sofia Martinez"),
        ("BA-004", "P104", "Oliver Brown"),
        ("BA-005", "P105", "Isabella Johnson"),
        ("BA-006", "P106", "Noah Davis"),
        ("BA-007", "P107", "Mia Thompson"),
    ]
    for tag, pid, name in aa401_bags:
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=pid, passenger_name=name,
            origin_flight="AA401", destination_flight="AA501",
            final_destination="LHR", current_location="BHS_ZONE_B",
            weight_kg=22.0,
        )
        store.CONNECTIONS[tag] = [TransferConnection(
            bag_tag=tag, passenger_id=pid,
            inbound_flight="AA401", outbound_flight="AA501",
            connection_window_minutes=max(0, 25 - 32),  # breached (-7 min)
            minimum_connection_time=25,
            is_at_risk=True,
            risk_reason="AA401 delayed 32 min, window to AA501 breached by 7 min",
        )]

    # ── Bags: AA402 → AA501 (3 bags, at risk but recoverable) ─────────────────
    # Window: 25 - 18 = 7 min remaining (< 25 MCT but exception routing saves them)

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
            connection_window_minutes=7,
            minimum_connection_time=25,
            is_at_risk=True,
            risk_reason="AA402 delayed 18 min, only 7 min remaining to AA501",
        )]

    # ── Bags: AA403 → AA502 (2 bags, NOT at risk — sufficient window) ──────────
    # Window: 40 - 11 = 29 min remaining (> 25 MCT — comfortable)

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
            connection_window_minutes=29,
            minimum_connection_time=25,
            is_at_risk=False,  # safe
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
