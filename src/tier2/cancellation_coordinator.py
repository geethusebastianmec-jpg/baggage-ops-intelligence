"""Tier 2 — Cancellation Coordinator.

Triggered when a flight is cancelled. Handles bags that were checked in
or already loaded on the cancelled flight.

  START
    └──[find_all_bags]          BHS: all bags on the cancelled flight
           ├──[rebook_bags]     MIP: optimal rerouting across available flights (parallel)
           └──[offload_loaded]  Ramp: initiate off-load for bags already in hold (parallel)
                   └──[notify_passengers]  MISSED + rebooking ETA
                          └──END

rebook_bags uses the Tier 2b MIP rerouter (src/solver/rerouter.py):
  - Groups bags by destination
  - Runs time-expanded network MIP across all available rerouting flights
  - Assigns bags optimally under capacity constraints (priority bags first)
  - Falls back to greedy if MIP solver unavailable
"""
from __future__ import annotations
from typing import Any, Annotated
import operator

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from src.models import BagStatus
from src.tools.bhs import BHSTool
from src.tools.ramp import RampTool
from src.tools.load_plan import LoadPlanTool
from src.tools.schedule import ScheduleTool
from src.tools.passenger_notify import PassengerNotifyTool
from src.tools import store

_bhs = BHSTool()
_ramp = RampTool()
_load_plan = LoadPlanTool()
_schedule = ScheduleTool()
_notify = PassengerNotifyTool()


class CancellationCoordinatorState(TypedDict, total=False):
    disruption_id: str
    flight_id: str
    reason: str
    # Set by find_all_bags
    all_bag_tags: list[str]
    loaded_bag_tags: list[str]      # bags already in aircraft hold
    unloaded_bag_tags: list[str]    # bags still in BHS
    # Set by parallel nodes
    rebooked: dict[str, str]        # bag_tag → new_flight_id
    rebooking_failed: list[str]
    offloaded: list[str]
    # Actions
    actions_taken: Annotated[list[dict[str, Any]], operator.add]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def find_all_bags(state: CancellationCoordinatorState) -> dict[str, Any]:
    """Tier 0 — identify every bag on the cancelled flight."""
    flight_id = state["flight_id"]

    all_tags = [
        tag for tag, bag in store.BAGS.items()
        if bag.origin_flight == flight_id or bag.destination_flight == flight_id
    ]

    loaded = [
        tag for tag in all_tags
        if store.BAGS[tag].status in (BagStatus.LOADED, BagStatus.CONFIRMED_LOADED)
    ]
    unloaded = [tag for tag in all_tags if tag not in loaded]

    return {
        "all_bag_tags": all_tags,
        "loaded_bag_tags": loaded,
        "unloaded_bag_tags": unloaded,
        "actions_taken": [{
            "node": "find_all_bags", "tool": "bhs",
            "result": (
                f"{flight_id} cancelled: {len(all_tags)} bags total. "
                f"{len(loaded)} already loaded (need off-load), "
                f"{len(unloaded)} in BHS (hold and rebook)."
            ),
            "all_bags": all_tags,
        }],
    }


def rebook_bags(state: CancellationCoordinatorState) -> dict[str, Any]:
    """Tier 2b — MIP optimal rerouting for cancelled-flight bags.

    Uses the time-expanded network MIP (src/solver/rerouter.py) to assign
    each bag to the best available rerouting flight, respecting capacity
    and prioritising by passenger priority weight.

    Falls back to the naive sequential lookup if no rerouting flights
    are seeded in the store.
    """
    from src.solver.rerouter import reroute_missed_bags, BagForRerouting

    flight_id = state["flight_id"]
    all_tags = state.get("all_bag_tags", [])

    # Build BagForRerouting objects
    bags_to_reroute: list[BagForRerouting] = []
    for tag in all_tags:
        bag = store.BAGS.get(tag)
        if bag:
            bags_to_reroute.append(BagForRerouting(
                bag_tag=tag,
                passenger_id=bag.passenger_id,
                destination=bag.final_destination or "",
                priority=bag.priority_weight,  # IATA-aligned: CREW=3.0, FIRST=2.4+, etc.
                earliest_ready_minutes=30,
            ))

    rebooked: dict[str, str] = {}
    failed: list[str] = []

    if bags_to_reroute and store.REROUTING_FLIGHTS:
        # MIP path — optimal rerouting across available flights
        result = reroute_missed_bags(
            bags_to_reroute,
            list(store.REROUTING_FLIGHTS),  # pass a copy; MIP updates capacity
            time_limit_seconds=5.0,
        )
        for tag, flight in result.assignments.items():
            if flight:
                _schedule.rebook_bag(tag, flight_id, flight)
                _bhs.mark_bag_missed(tag)
                rebooked[tag] = flight
            else:
                failed.append(tag)
        reasoning = result.reasoning
    else:
        # Fallback — naive sequential lookup (original stub behaviour)
        flight = store.FLIGHTS.get(flight_id)
        origin = flight.origin if flight else "JFK"
        for bag_obj in bags_to_reroute:
            next_flight = _schedule.find_next_flight(origin, bag_obj.destination)
            if next_flight:
                nf_id = next_flight["flight_id"]
                _schedule.rebook_bag(bag_obj.bag_tag, flight_id, nf_id)
                _bhs.mark_bag_missed(bag_obj.bag_tag)
                rebooked[bag_obj.bag_tag] = nf_id
            else:
                failed.append(bag_obj.bag_tag)
        reasoning = "Fallback: no rerouting flights seeded — used naive sequential lookup."

    return {
        "rebooked": rebooked,
        "rebooking_failed": failed,
        "actions_taken": [{
            "node": "rebook_bags", "tool": "mip_rerouter+schedule+bhs",
            "result": (
                f"MIP rerouting: {len(rebooked)}/{len(all_tags)} bags assigned to "
                f"next available flights. Failed: {len(failed)}. {reasoning}"
            ),
            "rebooked_count": len(rebooked),
        }],
    }


def offload_loaded(state: CancellationCoordinatorState) -> dict[str, Any]:
    """Tier 1 — initiate off-load for bags already physically in the aircraft hold."""
    loaded = state.get("loaded_bag_tags", [])
    flight_id = state["flight_id"]

    if not loaded:
        return {
            "offloaded": [],
            "actions_taken": [{"node": "offload_loaded",
                               "result": "No bags in hold to offload"}],
        }

    # Remove bags from load plan
    lp_updated = _load_plan.remove_bags(flight_id, loaded)
    # Dispatch ramp crew to physically remove bags
    zone = "B"
    crew = _ramp.get_crew_availability(zone)
    if crew and crew.can_take_exception:
        ticket = _ramp.assign_exception_task(loaded, flight_id, "OFFLOAD", zone)
        result_note = f"Ramp ticket {ticket.ticket_id} issued." if ticket else "No crew for offload."
    else:
        result_note = "No crew available — manual offload required."

    for tag in loaded:
        bag = store.BAGS.get(tag)
        if bag:
            store.BAGS[tag] = bag.model_copy(update={"status": BagStatus.OFFLOADED})

    return {
        "offloaded": loaded,
        "actions_taken": [{
            "node": "offload_loaded", "tool": "ramp+load_plan",
            "result": f"Initiated offload of {len(loaded)} bags from {flight_id}. {result_note}",
            "bag_tags": loaded,
        }],
    }


def notify_passengers(state: CancellationCoordinatorState) -> dict[str, Any]:
    """Tier 1 — notify every passenger: MISSED + rebooking flight."""
    all_tags = state.get("all_bag_tags", [])
    rebooked = state.get("rebooked", {})
    notified: list[str] = []

    for tag in all_tags:
        bag = store.BAGS.get(tag)
        if not bag:
            continue
        new_flight = rebooked.get(tag, "next available flight")
        _notify.notify_bag_missed(bag.passenger_id, tag, new_flight)
        notified.append(bag.passenger_id)

    return {
        "actions_taken": [{
            "node": "notify_passengers", "tool": "passenger_notify",
            "result": (
                f"Notified {len(notified)} passengers. "
                f"{len(rebooked)} have confirmed rebooking."
            ),
            "passengers_notified": notified,
        }],
    }


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_cancellation_coordinator() -> StateGraph:
    graph = StateGraph(CancellationCoordinatorState)

    graph.add_node("find_all_bags", find_all_bags)
    graph.add_node("rebook_bags", rebook_bags)
    graph.add_node("offload_loaded", offload_loaded)
    graph.add_node("notify_passengers", notify_passengers)

    graph.add_edge(START, "find_all_bags")
    # Parallel: rebook + offload simultaneously
    graph.add_edge("find_all_bags", "rebook_bags")
    graph.add_edge("find_all_bags", "offload_loaded")
    # Converge at passenger notification
    graph.add_edge("rebook_bags", "notify_passengers")
    graph.add_edge("offload_loaded", "notify_passengers")
    graph.add_edge("notify_passengers", END)

    return graph


cancellation_coordinator = build_cancellation_coordinator().compile()
