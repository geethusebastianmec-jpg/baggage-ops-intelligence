"""Tests for Tier 2b MIP rerouter — bag-to-flight assignment.

Verifies:
  1. Basic assignment — bags get assigned to correct destination flights
  2. Capacity constraint — MIP cannot assign more bags than flight capacity
  3. Priority — higher-priority bags assigned first when capacity is limited
  4. Timing — bags not assigned to flights that depart before bag is ready
  5. Destination filtering — bag only assigned to flights with matching destination
  6. All-stranded — returns None for all bags when no viable flight exists
  7. Integration with cancellation coordinator using store.REROUTING_FLIGHTS
"""
import pytest
from src.solver.rerouter import reroute_missed_bags, BagForRerouting, FlightLeg


def _bag(tag: str, dest: str, priority: float = 1.0, earliest: int = 0) -> BagForRerouting:
    return BagForRerouting(bag_tag=tag, passenger_id=f"P-{tag}",
                           destination=dest, priority=priority,
                           earliest_ready_minutes=earliest)


def _flight(fid: str, dest: str, departs: int, cap: int) -> FlightLeg:
    return FlightLeg(flight_id=fid, origin="JFK", destination=dest,
                     departs_in_minutes=departs, remaining_capacity=cap)


# ── Basic assignment ──────────────────────────────────────────────────────────

def test_assigns_bag_to_correct_destination():
    bags = [_bag("BA-001", "LHR"), _bag("BA-002", "CDG")]
    flights = [_flight("AA503", "LHR", 120, 10), _flight("AA504", "CDG", 240, 10)]
    result = reroute_missed_bags(bags, flights)
    assert result.assignments["BA-001"] == "AA503"
    assert result.assignments["BA-002"] == "AA504"
    assert result.bags_rerouted == 2
    assert result.bags_stranded == 0


def test_does_not_assign_wrong_destination():
    bags = [_bag("BA-001", "LHR")]
    flights = [_flight("AA504", "CDG", 120, 10)]  # CDG, not LHR
    result = reroute_missed_bags(bags, flights)
    assert result.assignments["BA-001"] is None
    assert result.bags_stranded == 1


# ── Capacity constraint ───────────────────────────────────────────────────────

def test_respects_flight_capacity():
    """5 bags, flight capacity = 3 → exactly 3 bags assigned."""
    bags = [_bag(f"BA-{i:03d}", "LHR") for i in range(5)]
    flights = [_flight("AA503", "LHR", 120, 3)]
    result = reroute_missed_bags(bags, flights)
    assert result.bags_rerouted == 3
    assert result.bags_stranded == 2
    assigned = [tag for tag, flt in result.assignments.items() if flt]
    assert len(assigned) == 3
    assert all(result.assignments[tag] == "AA503" for tag in assigned)


def test_distributes_across_multiple_flights():
    """3 bags, two flights each with capacity 2 → 3 assigned."""
    bags = [_bag(f"BA-{i:03d}", "LHR") for i in range(3)]
    flights = [_flight("AA503", "LHR", 120, 2), _flight("AA601", "LHR", 480, 2)]
    result = reroute_missed_bags(bags, flights)
    assert result.bags_rerouted == 3
    assert result.bags_stranded == 0


# ── Priority ──────────────────────────────────────────────────────────────────

def test_higher_priority_bags_get_assigned_first():
    """4 bags, capacity = 2. VIP bags (priority=2.0) should be chosen over normal."""
    bags = [
        _bag("NORMAL-1", "LHR", priority=1.0),
        _bag("VIP-1",    "LHR", priority=2.0),
        _bag("NORMAL-2", "LHR", priority=1.0),
        _bag("VIP-2",    "LHR", priority=2.0),
    ]
    flights = [_flight("AA503", "LHR", 120, 2)]
    result = reroute_missed_bags(bags, flights)
    assert result.bags_rerouted == 2
    # VIP bags should be the ones assigned
    assert result.assignments["VIP-1"] == "AA503"
    assert result.assignments["VIP-2"] == "AA503"
    assert result.assignments["NORMAL-1"] is None
    assert result.assignments["NORMAL-2"] is None


def test_earlier_flight_preferred_for_equal_priority():
    """Two flights to same destination — bag should go on earlier flight."""
    bags = [_bag("BA-001", "LHR")]
    flights = [
        _flight("AA601", "LHR", 480, 10),   # later
        _flight("AA503", "LHR", 120, 10),   # earlier
    ]
    result = reroute_missed_bags(bags, flights)
    # MIP applies delay penalty — earlier flight should win
    assert result.assignments["BA-001"] == "AA503"


# ── Timing constraint ─────────────────────────────────────────────────────────

def test_bag_not_assigned_to_flight_departing_before_ready():
    bags = [_bag("BA-001", "LHR", earliest=60)]   # bag needs 60 min
    flights = [
        _flight("AA503", "LHR", 30, 10),    # departs in 30 min — too early
        _flight("AA601", "LHR", 480, 10),   # departs in 8 hours — OK
    ]
    result = reroute_missed_bags(bags, flights)
    assert result.assignments["BA-001"] == "AA601"


def test_all_flights_too_early_returns_stranded():
    bags = [_bag("BA-001", "LHR", earliest=120)]
    flights = [_flight("AA503", "LHR", 60, 10)]   # departs before bag ready
    result = reroute_missed_bags(bags, flights)
    assert result.assignments["BA-001"] is None
    assert result.bags_stranded == 1


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_bags_returns_cleanly():
    result = reroute_missed_bags([], [_flight("AA503", "LHR", 120, 10)])
    assert result.bags_rerouted == 0
    assert result.solver_status == 'OPTIMAL'


def test_no_flights_returns_all_stranded():
    bags = [_bag("BA-001", "LHR"), _bag("BA-002", "LHR")]
    result = reroute_missed_bags(bags, [])
    assert result.bags_stranded == 2
    assert all(v is None for v in result.assignments.values())


# ── Cancellation integration ──────────────────────────────────────────────────

def test_cancellation_coordinator_uses_mip_rerouter():
    """Full coordinator run: cancelled flight, MIP assigns bags to rerouting flights."""
    from datetime import datetime, timezone, timedelta
    from src.tools import store
    from src.tools.passenger_notify import PassengerNotifyTool
    from src.models import Bag, BagStatus, Flight, FlightStatus, LoadPlan

    store.reset()
    PassengerNotifyTool.clear()
    now = datetime.now(timezone.utc)

    store.FLIGHTS["AA401"] = Flight(
        flight_id="AA401", airline="AA", origin="ORD", destination="JFK",
        scheduled_departure=now, estimated_departure=now, gate="B4", terminal="B",
    )
    for i, tag in enumerate(["BA-C1", "BA-C2", "BA-C3"]):
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=f"PC0{i}", passenger_name=f"Cancel Pax {i}",
            origin_flight="AA401", destination_flight=None,
            final_destination="LHR", current_location="BHS_ZONE_B",
        )
    store.LOAD_PLANS["AA401"] = LoadPlan(
        flight_id="AA401", aircraft_type="B737",
        max_weight_kg=15000.0, current_weight_kg=60.0, bag_count=3,
    )
    store.CREW_STATUS["B"] = __import__('src.models', fromlist=['CrewStatus']).CrewStatus(
        zone="B", available_crew=3, total_crew=5, active_tasks=0, can_take_exception=True
    )

    # Seed rerouting flights — only capacity 2, so one bag strands
    store.REROUTING_FLIGHTS.extend([
        FlightLeg("AA503", "JFK", "LHR", departs_in_minutes=120, remaining_capacity=2),
    ])

    from src.tier2.cancellation_coordinator import build_cancellation_coordinator
    result = build_cancellation_coordinator().compile().invoke({
        "disruption_id": "d-mip-001",
        "flight_id": "AA401",
        "reason": "WEATHER",
        "actions_taken": [],
    })

    node_names = [a["node"] for a in result["actions_taken"]]
    assert "rebook_bags" in node_names

    # Exactly 2 bags rebooked (capacity=2), 1 stranded
    rebooked = result.get("rebooked", {})
    assert len(rebooked) == 2
    assert all(v == "AA503" for v in rebooked.values())

    # All 3 passengers notified (missed)
    sent = PassengerNotifyTool.get_sent()
    assert len([n for n in sent if n["type"] == "MISSED"]) == 3
