"""Tier 2 — Ramp Domain Coordinator.

Triggered by BaggageExceptionEvent: physically transfer flagged bags.

  START → check_crew → [assign_task | escalate] → confirm_task → END
"""
from __future__ import annotations
from typing import Any

from langgraph.graph import StateGraph, START, END

from src.tier2.state import RampCoordinatorState
from src.tools.ramp import RampTool

_ramp = RampTool()


def check_crew(state: RampCoordinatorState) -> dict[str, Any]:
    zone = state.get("zone", "B")
    crew = _ramp.get_crew_availability(zone)
    if not crew:
        return {
            "error": f"No crew data for zone {zone}",
            "actions_taken": [{"node": "check_crew", "result": f"ERROR: no crew data for zone {zone}"}],
        }
    return {
        "actions_taken": [{
            "node": "check_crew",
            "tool": "ramp",
            "result": f"Zone {zone}: {crew.available_crew}/{crew.total_crew} crew, can_take={crew.can_take_exception}",
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
    return {
        "task_ticket": None,
        "actions_taken": [{
            "node": "escalate",
            "result": "Ramp crew unavailable — escalated to supervisor for manual resolution",
        }],
    }


def _route_after_crew_check(state: RampCoordinatorState) -> str:
    zone = state.get("zone", "B")
    from src.tools import store
    crew = store.CREW_STATUS.get(zone)
    if crew and crew.can_take_exception:
        return "assign_task"
    return "escalate"


def build_ramp_coordinator() -> StateGraph:
    graph = StateGraph(RampCoordinatorState)
    graph.add_node("check_crew", check_crew)
    graph.add_node("assign_task", assign_task)
    graph.add_node("escalate", escalate)

    graph.add_edge(START, "check_crew")
    graph.add_conditional_edges("check_crew", _route_after_crew_check)
    graph.add_edge("assign_task", END)
    graph.add_edge("escalate", END)
    return graph


ramp_coordinator = build_ramp_coordinator().compile()
