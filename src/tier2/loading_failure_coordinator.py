"""Tier 2 — Loading Failure Coordinator.

Triggered when a bag was checked in but never physically loaded onto the flight.
Detected at departure via manifest check. Covers 16% of all mishandling.

  START
    └──[locate_bag]            BHS: where is the bag right now?
           └──[check_flight]   AODB: is the flight still at gate?
                  ├──[emergency_load]   Ramp: rush bag to aircraft (still at gate)
                  └──[rebook_bag]       Find next flight to destination
                         └──[notify_passenger]  MISSED + delivery ETA
                                └──END

All Tier 1 — deterministic rules, no LLM.
"""
from __future__ import annotations
from typing import Any, Annotated
import operator

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from src.models import BagStatus
from src.tools.aodb import AODBTool
from src.tools.bhs import BHSTool
from src.tools.ramp import RampTool
from src.tools.passenger_notify import PassengerNotifyTool
from src.tools.load_plan import LoadPlanTool
from src.tools import store

_bhs = BHSTool()
_aodb = AODBTool()
_ramp = RampTool()
_notify = PassengerNotifyTool()
_load_plan = LoadPlanTool()

# Minimum minutes at gate needed to emergency-load a bag
EMERGENCY_LOAD_MIN_WINDOW = 10


class LoadingFailureCoordinatorState(TypedDict, total=False):
    disruption_id: str
    bag_tag: str
    flight_id: str
    # Set by locate_bag
    bag_found: bool
    bag_location: str
    # Set by check_flight
    flight_at_gate: bool
    gate_window_minutes: int
    # Set by branch nodes
    emergency_loaded: bool
    rebooked: bool
    next_flight: str
    # Actions
    actions_taken: Annotated[list[dict[str, Any]], operator.add]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def locate_bag(state: LoadingFailureCoordinatorState) -> dict[str, Any]:
    """Tier 0 — find where the bag currently is in the BHS."""
    tag = state["bag_tag"]
    bag = _bhs.query_bag(tag)
    found = bag is not None
    location = bag.current_location if bag else "UNKNOWN"
    return {
        "bag_found": found,
        "bag_location": location,
        "actions_taken": [{
            "node": "locate_bag", "tool": "bhs",
            "result": f"{tag}: {'found at ' + location if found else 'NOT FOUND in BHS'}",
        }],
    }


def check_flight(state: LoadingFailureCoordinatorState) -> dict[str, Any]:
    """Tier 0 — is the flight still at the gate with enough time to load?"""
    flight_id = state["flight_id"]
    window = _aodb.get_departure_window_minutes(flight_id)
    at_gate = window >= EMERGENCY_LOAD_MIN_WINDOW
    return {
        "flight_at_gate": at_gate,
        "gate_window_minutes": window,
        "actions_taken": [{
            "node": "check_flight", "tool": "aodb",
            "result": (
                f"{flight_id}: {window} min until departure. "
                f"Emergency load {'POSSIBLE' if at_gate else 'TOO LATE'}."
            ),
        }],
    }


def emergency_load(state: LoadingFailureCoordinatorState) -> dict[str, Any]:
    """Tier 1 — dispatch ramp crew to rush the bag to the aircraft."""
    tag = state["bag_tag"]
    flight_id = state["flight_id"]
    zone = "B"

    crew = _ramp.get_crew_availability(zone)
    if crew and crew.can_take_exception:
        ticket = _ramp.assign_exception_task([tag], "ORIGIN", flight_id, zone)
        # Update bag status
        bag = store.BAGS.get(tag)
        if bag:
            store.BAGS[tag] = bag.model_copy(update={"status": BagStatus.EXCEPTION})
        return {
            "emergency_loaded": ticket is not None,
            "actions_taken": [{
                "node": "emergency_load", "tool": "ramp+bhs",
                "result": (
                    f"Emergency load dispatched for {tag} onto {flight_id}. "
                    f"Ramp ticket: {ticket.ticket_id if ticket else 'FAILED'}."
                ),
            }],
        }
    return {
        "emergency_loaded": False,
        "actions_taken": [{
            "node": "emergency_load",
            "result": f"No crew available for emergency load of {tag}",
        }],
    }


def rebook_bag(state: LoadingFailureCoordinatorState) -> dict[str, Any]:
    """Tier 2b — MIP optimal rerouting for a single bag that was never loaded.

    Runs the same MIP rerouter as the cancellation coordinator but for
    one bag. Priority is elevated slightly (1.2) because a loading failure
    is operationally urgent — the passenger was expecting the bag on this flight.
    """
    from src.solver.rerouter import reroute_missed_bags, BagForRerouting

    tag = state["bag_tag"]
    flight_id = state["flight_id"]
    bag = store.BAGS.get(tag)

    if not bag:
        return {
            "rebooked": False, "next_flight": "",
            "actions_taken": [{"node": "rebook_bag", "result": f"Bag {tag} not found"}],
        }

    _bhs.mark_bag_missed(tag)

    if store.REROUTING_FLIGHTS:
        result = reroute_missed_bags(
            [BagForRerouting(
                bag_tag=tag,
                passenger_id=bag.passenger_id,
                destination=bag.final_destination or "",
                priority=1.2,                # slightly elevated — loading failure is urgent
                earliest_ready_minutes=20,   # faster processing (bag is still in BHS)
            )],
            list(store.REROUTING_FLIGHTS),
            time_limit_seconds=2.0,
        )
        next_flight = result.assignments.get(tag)
        if next_flight:
            _schedule.rebook_bag(tag, flight_id, next_flight)
            return {
                "rebooked": True, "next_flight": next_flight,
                "actions_taken": [{
                    "node": "rebook_bag", "tool": "mip_rerouter+bhs",
                    "result": f"{tag} rerouted via MIP → {next_flight}. {result.reasoning}",
                    "next_flight": next_flight,
                }],
            }

    # Fallback if no rerouting flights available
    next_flight = f"{flight_id[:-2]}NEXT"
    return {
        "rebooked": True, "next_flight": next_flight,
        "actions_taken": [{
            "node": "rebook_bag", "tool": "bhs",
            "result": f"{tag} marked missed on {flight_id}. Fallback booking: {next_flight}.",
            "next_flight": next_flight,
        }],
    }


def notify_passenger(state: LoadingFailureCoordinatorState) -> dict[str, Any]:
    """Tier 1 — notify passenger of the outcome."""
    tag = state["bag_tag"]
    bag = store.BAGS.get(tag)
    if not bag:
        return {"actions_taken": [{"node": "notify_passenger", "result": "No bag record found"}]}

    emergency_loaded = state.get("emergency_loaded", False)
    next_flight = state.get("next_flight", "next available flight")

    if emergency_loaded:
        _notify.notify_bag_recovered(bag.passenger_id, tag)
        result = f"Passenger {bag.passenger_id} notified: bag {tag} emergency loaded."
    else:
        _notify.notify_bag_missed(bag.passenger_id, tag, next_flight)
        result = f"Passenger {bag.passenger_id} notified: bag {tag} missed, travelling via {next_flight}."

    return {
        "actions_taken": [{"node": "notify_passenger", "tool": "passenger_notify", "result": result}],
    }


def _branch_after_check(state: LoadingFailureCoordinatorState) -> str:
    """If flight still at gate with enough time → emergency load. Else rebook."""
    return "emergency_load" if state.get("flight_at_gate", False) else "rebook_bag"


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_loading_failure_coordinator() -> StateGraph:
    graph = StateGraph(LoadingFailureCoordinatorState)

    graph.add_node("locate_bag", locate_bag)
    graph.add_node("check_flight", check_flight)
    graph.add_node("emergency_load", emergency_load)
    graph.add_node("rebook_bag", rebook_bag)
    graph.add_node("notify_passenger", notify_passenger)

    graph.add_edge(START, "locate_bag")
    graph.add_edge("locate_bag", "check_flight")
    graph.add_conditional_edges("check_flight", _branch_after_check)
    graph.add_edge("emergency_load", "notify_passenger")
    graph.add_edge("rebook_bag", "notify_passenger")
    graph.add_edge("notify_passenger", END)

    return graph


loading_failure_coordinator = build_loading_failure_coordinator().compile()
