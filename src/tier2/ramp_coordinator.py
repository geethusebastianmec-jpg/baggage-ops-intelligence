"""Tier 2 — Ramp Domain Coordinator.

Triggered by BaggageExceptionEvent: physically transfer flagged bags.

  START → check_crew → [assign_task | pull_adjacent | escalate] → END

W6 crew shortage handling:
  If primary zone has no crew → check adjacent zones before escalating.
  Adjacent zone map: B↔C, C↔B, D↔C (simplified for demo).
  Pulls crew from the first adjacent zone that can take exception work.
"""
from __future__ import annotations
from typing import Any

from langgraph.graph import StateGraph, START, END

from src.tier2.state import RampCoordinatorState
from src.tools.ramp import RampTool

_ramp = RampTool()

# Simplified adjacency: which zones to try if primary is unavailable
_ADJACENT_ZONES: dict[str, list[str]] = {
    "A": ["B"],
    "B": ["C", "A"],
    "C": ["B", "D"],
    "D": ["C"],
}


def check_crew(state: RampCoordinatorState) -> dict[str, Any]:
    zone = state.get("zone", "B")
    crew = _ramp.get_crew_availability(zone)
    if not crew:
        return {
            "error": f"No crew data for zone {zone}",
            "actions_taken": [{"node": "check_crew",
                               "result": f"ERROR: no crew data for zone {zone}"}],
        }
    return {
        "actions_taken": [{
            "node": "check_crew",
            "tool": "ramp",
            "result": (
                f"Zone {zone}: {crew.available_crew}/{crew.total_crew} crew, "
                f"can_take={crew.can_take_exception}"
            ),
        }],
    }


def pull_adjacent_crew(state: RampCoordinatorState) -> dict[str, Any]:
    """W6: crew shortage — check adjacent zones and pull the first available."""
    primary_zone = state.get("zone", "B")
    bag_tags = state.get("bag_tags", [])
    from_flight = state.get("from_flight", "")
    to_flight = state.get("to_flight", "")

    for adjacent in _ADJACENT_ZONES.get(primary_zone, []):
        crew = _ramp.get_crew_availability(adjacent)
        if crew and crew.can_take_exception:
            ticket = _ramp.assign_exception_task(bag_tags, from_flight, to_flight, adjacent)
            if ticket:
                return {
                    "task_ticket": ticket.model_dump(),
                    "zone": adjacent,
                    "actions_taken": [{
                        "node": "pull_adjacent_crew",
                        "tool": "ramp",
                        "result": (
                            f"Crew shortage in zone {primary_zone} — "
                            f"pulled crew from adjacent zone {adjacent}. "
                            f"Task {ticket.ticket_id} assigned, ETA {ticket.eta_minutes} min."
                        ),
                        "original_zone": primary_zone,
                        "assigned_zone": adjacent,
                        "ticket_id": ticket.ticket_id,
                    }],
                }

    # No adjacent crew available either
    return {
        "task_ticket": None,
        "actions_taken": [{
            "node": "pull_adjacent_crew",
            "result": (
                f"No crew in zone {primary_zone} or adjacent zones "
                f"{_ADJACENT_ZONES.get(primary_zone, [])} — escalating."
            ),
        }],
    }


def assign_task(state: RampCoordinatorState) -> dict[str, Any]:
    bag_tags = state.get("bag_tags", [])
    from_flight = state.get("from_flight", "")
    to_flight = state.get("to_flight", "")
    zone = state.get("zone", "B")

    ticket = _ramp.assign_exception_task(bag_tags, from_flight, to_flight, zone)
    if not ticket:
        return {
            "task_ticket": None,
            "error": "Ramp crew unavailable — could not assign task",
            "actions_taken": [{"node": "assign_task", "result": "FAILED: crew unavailable"}],
        }
    return {
        "task_ticket": ticket.model_dump(),
        "actions_taken": [{
            "node": "assign_task",
            "tool": "ramp",
            "result": f"Task {ticket.ticket_id} assigned — ETA {ticket.eta_minutes} min",
            "ticket_id": ticket.ticket_id,
        }],
    }


def escalate(state: RampCoordinatorState) -> dict[str, Any]:
    zone = state.get("zone", "B")
    return {
        "task_ticket": None,
        "actions_taken": [{
            "node": "escalate",
            "result": (
                f"Crew shortage: no crew in zone {zone} or adjacent zones. "
                "Escalated to AOCC supervisor for manual resolution."
            ),
        }],
    }


def _route_after_crew_check(state: RampCoordinatorState) -> str:
    from src.tools import store
    zone = state.get("zone", "B")
    crew = store.CREW_STATUS.get(zone)
    if crew and crew.can_take_exception:
        return "assign_task"
    # Primary zone has no crew — try adjacent before escalating
    for adjacent in _ADJACENT_ZONES.get(zone, []):
        adj_crew = store.CREW_STATUS.get(adjacent)
        if adj_crew and adj_crew.can_take_exception:
            return "pull_adjacent_crew"
    return "escalate"


def build_ramp_coordinator() -> StateGraph:
    graph = StateGraph(RampCoordinatorState)
    graph.add_node("check_crew", check_crew)
    graph.add_node("assign_task", assign_task)
    graph.add_node("pull_adjacent_crew", pull_adjacent_crew)
    graph.add_node("escalate", escalate)

    graph.add_edge(START, "check_crew")
    graph.add_conditional_edges("check_crew", _route_after_crew_check)
    graph.add_edge("assign_task", END)
    graph.add_edge("pull_adjacent_crew", END)
    graph.add_edge("escalate", END)
    return graph


ramp_coordinator = build_ramp_coordinator().compile()
