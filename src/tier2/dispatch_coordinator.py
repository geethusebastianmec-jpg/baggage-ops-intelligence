"""Tier 2 — Dispatch Domain Coordinator.

Decides whether to hold a departure or let it go.
All decisions are deterministic (Tier 1 cost comparison). No LLM.

  START → [fetch_load_plan ‖ fetch_departure_window] → decide_hold → END

Hold policy (Tier 1 cost comparison):
  1. window <= 5 min               → DEPART (too late regardless of bags)
  2. recoverable == 0              → DEPART (nothing to wait for)
  3. bags_saved × $150 > hold × $500 → HOLD (saving bags is worth the delay)
  4. Otherwise                     → DEPART

Costs from industry data:
  miss_cost  = $150 per bag (recovery, delivery, claims handling)
  delay_cost = $500 per minute (fuel burn, crew overtime, network ripple)
"""
from __future__ import annotations
from typing import Any

from langgraph.graph import StateGraph, START, END

from src.tier2.state import DispatchCoordinatorState
from src.tools.aodb import AODBTool
from src.tools.load_plan import LoadPlanTool

_aodb = AODBTool()
_load_plan = LoadPlanTool()

MISS_COST_PER_BAG = 150     # $ per missed bag
DELAY_COST_PER_MINUTE = 500  # $ per minute of departure hold
STANDARD_HOLD_MINUTES = 5    # assumed hold duration for cost comparison


def fetch_load_plan(state: DispatchCoordinatorState) -> dict[str, Any]:
    flight_id = state["flight_id"]
    lp = _load_plan.get_load_plan(flight_id)
    return {
        "load_plan": lp.model_dump() if lp else None,
        "actions_taken": [{
            "node": "fetch_load_plan", "tool": "load_plan",
            "result": (
                f"{flight_id}: {lp.bag_count} bags, {len(lp.pending_bags)} pending"
                if lp else "No load plan"
            ),
        }],
    }


def fetch_departure_window(state: DispatchCoordinatorState) -> dict[str, Any]:
    flight_id = state["flight_id"]
    window = _aodb.get_departure_window_minutes(flight_id)
    return {
        "departure_window_minutes": window,
        "actions_taken": [{
            "node": "fetch_departure_window", "tool": "aodb",
            "result": f"{flight_id} departs in {window} min",
        }],
    }


def decide_hold(state: DispatchCoordinatorState) -> dict[str, Any]:
    """Tier 1 cost comparison — no LLM required."""
    recoverable = state.get("recoverable_bag_count", 0)
    window = state.get("departure_window_minutes", 0)
    lp = state.get("load_plan")
    pending = len(lp.get("pending_bags", [])) if lp else 0

    # Rule 1: too late to hold regardless
    if window <= 5:
        return _decision("DEPART",
                         f"Window {window} min — insufficient time to hold.", state)

    # Rule 2: nothing to save
    if recoverable == 0 and pending == 0:
        return _decision("DEPART", "No recoverable bags pending.", state)

    # Rule 3: cost comparison
    # How many bags can we save with a standard hold?
    bags_to_save = max(recoverable, pending)
    save_value = bags_to_save * MISS_COST_PER_BAG
    hold_cost = STANDARD_HOLD_MINUTES * DELAY_COST_PER_MINUTE  # $2,500 for 5-min hold

    if save_value > hold_cost:
        return _decision(
            "HOLD",
            f"{bags_to_save} bags × ${MISS_COST_PER_BAG} = ${save_value:,} "
            f"> {STANDARD_HOLD_MINUTES}-min hold cost ${hold_cost:,} — hold approved.",
            state,
        )

    return _decision(
        "DEPART",
        f"{bags_to_save} bags × ${MISS_COST_PER_BAG} = ${save_value:,} "
        f"< {STANDARD_HOLD_MINUTES}-min hold cost ${hold_cost:,} — not worth holding.",
        state,
    )


def _decision(decision: str, reasoning: str, state: dict) -> dict[str, Any]:
    return {
        "hold_decision": decision,
        "hold_reasoning": reasoning,
        "actions_taken": [{"node": "decide_hold", "result": f"{decision}: {reasoning}"}],
    }


def build_dispatch_coordinator() -> StateGraph:
    graph = StateGraph(DispatchCoordinatorState)
    graph.add_node("fetch_load_plan", fetch_load_plan)
    graph.add_node("fetch_departure_window", fetch_departure_window)
    graph.add_node("decide_hold", decide_hold)

    graph.add_edge(START, "fetch_load_plan")
    graph.add_edge(START, "fetch_departure_window")
    graph.add_edge("fetch_load_plan", "decide_hold")
    graph.add_edge("fetch_departure_window", "decide_hold")
    graph.add_edge("decide_hold", END)
    return graph


dispatch_coordinator = build_dispatch_coordinator().compile()
