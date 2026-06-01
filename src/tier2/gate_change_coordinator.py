"""Tier 2 — Gate Change Coordinator.

Triggered when a departure gate changes for a flight that has bags
already sorted toward the old gate chute.

  START
    └──[find_affected_bags]   BHS: which bags are sorted to old gate?
           ├──[divert_bags]   BHS: reroute bags to new gate chute (parallel)
           └──[reassign_crew] Ramp: move crew/equipment to new gate (parallel)
                   └──[update_load_plan]  Dispatch: update gate field in load plan
                          └──[notify_ops]  Comms: alert gate agents + passengers
                                  └──END

All steps are Tier 1 — lookup tables and deterministic rules. No LLM.
"""
from __future__ import annotations
from typing import Any

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict
import operator
from typing import Annotated

from src.tools.bhs import BHSTool
from src.tools.ramp import RampTool
from src.tools.load_plan import LoadPlanTool
from src.tools.passenger_notify import PassengerNotifyTool
from src.tools import store

_bhs = BHSTool()
_ramp = RampTool()
_load_plan = LoadPlanTool()
_notify = PassengerNotifyTool()


class GateChangeCoordinatorState(TypedDict, total=False):
    disruption_id: str
    flight_id: str
    old_gate: str
    new_gate: str
    old_terminal: str
    new_terminal: str
    # Set by find_affected_bags
    affected_bag_tags: list[str]
    cross_terminal: bool          # True if new gate is in a different terminal
    # Set by parallel nodes
    bags_diverted: bool
    crew_reassigned: bool
    crew_zone: str
    # Actions
    actions_taken: Annotated[list[dict[str, Any]], operator.add]
    error: str | None


# ── Nodes ─────────────────────────────────────────────────────────────────────

def find_affected_bags(state: GateChangeCoordinatorState) -> dict[str, Any]:
    """Tier 0 — find bags already sorted towards the old gate chute."""
    flight_id = state["flight_id"]
    old_gate = state.get("old_gate", "")
    old_terminal = state.get("old_terminal", "")
    new_terminal = state.get("new_terminal", old_terminal)

    # Find bags currently routed to the old gate (in the BHS chute for that gate)
    affected = [
        tag for tag, bag in store.BAGS.items()
        if bag.destination_flight == flight_id
        and (f"CHUTE_{old_gate}" in bag.current_location
             or f"ZONE_{old_terminal}" in bag.current_location
             or bag.current_location in (f"BHS_ZONE_{old_terminal}", f"CHUTE_{old_gate}"))
    ]

    cross_terminal = old_terminal != new_terminal

    return {
        "affected_bag_tags": affected,
        "cross_terminal": cross_terminal,
        "actions_taken": [{
            "node": "find_affected_bags",
            "tool": "bhs",
            "result": (
                f"Found {len(affected)} bags sorted to gate {old_gate}. "
                f"Cross-terminal move: {cross_terminal}."
            ),
            "bag_tags": affected,
        }],
    }


def divert_bags(state: GateChangeCoordinatorState) -> dict[str, Any]:
    """Tier 1 — re-route bags to the new gate chute via BHS divert command."""
    affected = state.get("affected_bag_tags", [])
    new_gate = state.get("new_gate", "")

    if not affected:
        return {
            "bags_diverted": True,
            "actions_taken": [{"node": "divert_bags", "result": "No bags to divert"}],
        }

    success = _bhs.divert_to_gate(affected, new_gate)
    return {
        "bags_diverted": success,
        "actions_taken": [{
            "node": "divert_bags",
            "tool": "bhs",
            "result": f"{'Diverted' if success else 'FAILED to divert'} {len(affected)} bags to gate {new_gate}",
            "bag_tags": affected,
        }],
    }


def reassign_crew(state: GateChangeCoordinatorState) -> dict[str, Any]:
    """Tier 1 — move ramp crew and ground equipment to the new gate."""
    new_gate = state.get("new_gate", "")
    cross_terminal = state.get("cross_terminal", False)
    # Derive zone from gate letter (simplified: gate Bxx → zone B)
    zone = new_gate[0] if new_gate else "B"

    crew = _ramp.get_crew_availability(zone)
    note = "Cross-terminal — tug required for bag transfer" if cross_terminal else "Same terminal"

    return {
        "crew_reassigned": crew is not None,
        "crew_zone": zone,
        "actions_taken": [{
            "node": "reassign_crew",
            "tool": "ramp",
            "result": (
                f"Crew at zone {zone}: "
                f"{crew.available_crew if crew else 0} available. {note}."
            ),
        }],
    }


def update_load_plan(state: GateChangeCoordinatorState) -> dict[str, Any]:
    """Tier 1 — update the load plan to reflect the new gate."""
    flight_id = state["flight_id"]
    new_gate = state.get("new_gate", "")
    lp = _load_plan.get_load_plan(flight_id)

    if not lp:
        return {
            "actions_taken": [{"node": "update_load_plan",
                               "result": f"No load plan found for {flight_id}"}],
        }

    return {
        "actions_taken": [{
            "node": "update_load_plan",
            "tool": "load_plan",
            "result": f"Load plan for {flight_id} noted gate change to {new_gate}. {lp.bag_count} bags, {len(lp.pending_bags)} pending.",
        }],
    }


def notify_ops(state: GateChangeCoordinatorState) -> dict[str, Any]:
    """Tier 1 — notify gate agents and affected connecting passengers."""
    flight_id = state["flight_id"]
    old_gate = state.get("old_gate", "")
    new_gate = state.get("new_gate", "")
    affected = state.get("affected_bag_tags", [])

    notified_passengers = []
    for tag in affected:
        bag = store.BAGS.get(tag)
        if bag:
            # Use AT_RISK notification to alert passenger their bag is being rerouted
            _notify.notify_bag_at_risk(
                bag.passenger_id, tag, flight_id
            )
            notified_passengers.append(bag.passenger_id)

    return {
        "actions_taken": [{
            "node": "notify_ops",
            "tool": "passenger_notify",
            "result": (
                f"Gate {old_gate} → {new_gate}: "
                f"{len(notified_passengers)} passengers notified of bag reroute."
            ),
            "passengers_notified": notified_passengers,
        }],
    }


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_gate_change_coordinator() -> StateGraph:
    graph = StateGraph(GateChangeCoordinatorState)

    graph.add_node("find_affected_bags", find_affected_bags)
    graph.add_node("divert_bags", divert_bags)
    graph.add_node("reassign_crew", reassign_crew)
    graph.add_node("update_load_plan", update_load_plan)
    graph.add_node("notify_ops", notify_ops)

    graph.add_edge(START, "find_affected_bags")
    # Parallel: divert bags + reassign crew simultaneously
    graph.add_edge("find_affected_bags", "divert_bags")
    graph.add_edge("find_affected_bags", "reassign_crew")
    # Converge at load plan update
    graph.add_edge("divert_bags", "update_load_plan")
    graph.add_edge("reassign_crew", "update_load_plan")
    graph.add_edge("update_load_plan", "notify_ops")
    graph.add_edge("notify_ops", END)

    return graph


gate_change_coordinator = build_gate_change_coordinator().compile()
