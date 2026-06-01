"""Tier 2 — Security Hold Coordinator.

Triggered when a CT scanner or TSA agent flags a bag for inspection.
This is primarily a compliance and handoff workflow — the system's job is
to prevent the bag from loading, notify the right people, and route the
outcome correctly once a human makes the clearance decision.

  START
    └──[place_hold]          BHS: pull bag from queue, mark SECURITY_HOLD
           └──[notify_all]   Notify passenger + baggage service agent   (parallel)
                  └──[await_decision]  Simulated HITL gate:
                                 CLEARED → rebook_on_next_flight
                                 REJECTED → escalate_to_authority
                                 └──END

Tier placement:
  - Tier 1 throughout (rule-based steps and lookup tables)
  - The human clearance decision is the only genuinely non-deterministic step,
    and it belongs to a human — not an LLM.
"""
from __future__ import annotations
from typing import Any, Annotated
import operator

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from src.models import BagStatus
from src.tools.bhs import BHSTool
from src.tools.schedule import ScheduleTool
from src.tools.passenger_notify import PassengerNotifyTool
from src.tools import store

_bhs = BHSTool()
_schedule = ScheduleTool()
_notify = PassengerNotifyTool()

# In production: CLEARED arrives as an async event from the security system.
# In demo: pre-configured per scenario via the `simulated_outcome` state field.
SIMULATED_OUTCOME_DEFAULT = "CLEARED"   # "CLEARED" or "REJECTED"


class SecurityHoldCoordinatorState(TypedDict, total=False):
    disruption_id: str
    bag_tag: str
    flight_id: str
    hold_reason: str
    # Simulated HITL outcome for demo (in production: driven by security system event)
    simulated_outcome: str          # "CLEARED" | "REJECTED"
    # Set by place_hold
    hold_placed: bool
    # Set by await_decision branch
    rebooked_on: str | None
    escalated: bool
    # Actions
    actions_taken: Annotated[list[dict[str, Any]], operator.add]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def place_hold(state: SecurityHoldCoordinatorState) -> dict[str, Any]:
    """Tier 1 — immediately prevent the bag from being loaded."""
    tag = state["bag_tag"]
    reason = state.get("hold_reason", "Security inspection required")
    success = _bhs.place_security_hold(tag, reason)
    return {
        "hold_placed": success,
        "actions_taken": [{
            "node": "place_hold", "tool": "bhs",
            "result": (
                f"Security hold {'placed' if success else 'FAILED'} on {tag}. "
                f"Reason: {reason}. Bag pulled from BHS queue."
            ),
        }],
    }


def notify_passenger(state: SecurityHoldCoordinatorState) -> dict[str, Any]:
    """Tier 1 — inform passenger their bag is being held for security inspection."""
    tag = state["bag_tag"]
    bag = store.BAGS.get(tag)
    if not bag:
        return {"actions_taken": [{"node": "notify_passenger", "result": "Bag not found"}]}

    # AT_RISK is the closest match — bag is held, outcome unknown
    _notify.notify_bag_at_risk(bag.passenger_id, tag, state.get("flight_id", ""))
    return {
        "actions_taken": [{
            "node": "notify_passenger", "tool": "passenger_notify",
            "result": f"Passenger {bag.passenger_id} notified: bag {tag} held for security inspection.",
        }],
    }


def notify_baggage_service(state: SecurityHoldCoordinatorState) -> dict[str, Any]:
    """Tier 1 — alert baggage service team + log compliance record."""
    tag = state["bag_tag"]
    reason = state.get("hold_reason", "Security inspection")
    store.ACTION_LOG.append({
        "tool": "compliance",
        "action": "security_hold_opened",
        "bag_tag": tag,
        "reason": reason,
        "requires_human_decision": True,
    })
    return {
        "actions_taken": [{
            "node": "notify_baggage_service", "tool": "compliance",
            "result": f"Baggage service alerted. Compliance record opened for {tag}. Human review required.",
        }],
    }


def rebook_on_next_flight(state: SecurityHoldCoordinatorState) -> dict[str, Any]:
    """Tier 1 — security cleared the bag; rebook on next available flight."""
    tag = state["bag_tag"]
    flight_id = state.get("flight_id", "")
    bag = store.BAGS.get(tag)

    if not bag:
        return {"rebooked_on": None,
                "actions_taken": [{"node": "rebook_on_next_flight", "result": "Bag not found"}]}

    _bhs.clear_security_hold(tag)

    next_flight = _schedule.find_next_flight(bag.current_location[:3] or "JFK",
                                              bag.final_destination or "")
    if next_flight:
        nf_id = next_flight["flight_id"]
        _schedule.rebook_bag(tag, flight_id, nf_id)
        _notify.notify_bag_missed(bag.passenger_id, tag, nf_id)
        return {
            "rebooked_on": nf_id,
            "escalated": False,
            "actions_taken": [{
                "node": "rebook_on_next_flight", "tool": "schedule+passenger_notify",
                "result": f"Security cleared. {tag} rebooked on {nf_id}. Passenger notified.",
            }],
        }

    return {
        "rebooked_on": None,
        "escalated": False,
        "actions_taken": [{"node": "rebook_on_next_flight",
                           "result": f"Security cleared but no next flight found for {tag}. Manual handling required."}],
    }


def escalate_to_authority(state: SecurityHoldCoordinatorState) -> dict[str, Any]:
    """Tier 1 — security rejected the bag; hand off to law enforcement protocol."""
    tag = state["bag_tag"]
    bag = store.BAGS.get(tag)

    if bag:
        store.BAGS[tag] = bag.model_copy(update={"status": BagStatus.MISSED})
        _notify.notify_bag_missed(bag.passenger_id, tag, "N/A — security seizure")

    store.ACTION_LOG.append({
        "tool": "compliance",
        "action": "security_rejected_escalated",
        "bag_tag": tag,
        "escalated_to": "TSA/LAW_ENFORCEMENT",
    })

    return {
        "rebooked_on": None,
        "escalated": True,
        "actions_taken": [{
            "node": "escalate_to_authority", "tool": "compliance+passenger_notify",
            "result": f"Security REJECTED {tag}. Escalated to law enforcement. Passenger notified (bag seized).",
        }],
    }


def _branch_on_outcome(state: SecurityHoldCoordinatorState) -> str:
    outcome = state.get("simulated_outcome", SIMULATED_OUTCOME_DEFAULT)
    return "rebook_on_next_flight" if outcome == "CLEARED" else "escalate_to_authority"


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_security_hold_coordinator() -> StateGraph:
    graph = StateGraph(SecurityHoldCoordinatorState)

    graph.add_node("place_hold", place_hold)
    graph.add_node("notify_passenger", notify_passenger)
    graph.add_node("notify_baggage_service", notify_baggage_service)
    graph.add_node("rebook_on_next_flight", rebook_on_next_flight)
    graph.add_node("escalate_to_authority", escalate_to_authority)

    graph.add_edge(START, "place_hold")
    # Parallel: notify passenger + notify baggage service simultaneously
    graph.add_edge("place_hold", "notify_passenger")
    graph.add_edge("place_hold", "notify_baggage_service")
    # Converge at HITL decision gate
    graph.add_conditional_edges("notify_passenger", _branch_on_outcome)
    graph.add_conditional_edges("notify_baggage_service", _branch_on_outcome)
    graph.add_edge("rebook_on_next_flight", END)
    graph.add_edge("escalate_to_authority", END)

    return graph


security_hold_coordinator = build_security_hold_coordinator().compile()
