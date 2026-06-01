"""Tier 2 — Baggage Domain Coordinator.

LangGraph DAG — all decision logic is deterministic (Tier 1 + Tier 2).
No LLM in this coordinator.

  START
    └──[prepare_context]     BHS: fetch at-risk connections for inbound flight
           ├──[fetch_departure]  AODB: departure window on outbound (parallel)
           └──[fetch_ramp]       Ramp: crew availability                (parallel)
                   └──[triage_and_optimize]
                          Tier 1: slack = window - move_time per bag
                          Tier 2: CP-SAT if crew contended (more bags than capacity)
                          ├──[route_bags]   Exception routing + ramp task + AT_RISK notify
                          └──[flag_missed]  Mark missed + MISSED passenger notify
                                  └──END
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, START, END

from src.models import FeasibilityVerdict
from src.solver.triage import triage_bags, has_contention, simultaneous_capacity
from src.solver.optimizer import solve_contended, BagForOptimization
from src.tier2.state import BaggageCoordinatorState
from src.tools.aodb import AODBTool
from src.tools.bhs import BHSTool
from src.tools.load_plan import LoadPlanTool
from src.tools.passenger_notify import PassengerNotifyTool
from src.tools.ramp import RampTool

_bhs = BHSTool()
_aodb = AODBTool()
_ramp = RampTool()
_notify = PassengerNotifyTool()
_load_plan = LoadPlanTool()


# ── Nodes ─────────────────────────────────────────────────────────────────────

def prepare_context(state: BaggageCoordinatorState) -> dict[str, Any]:
    """Tier 0 read — query BHS for at-risk connections on the inbound flight."""
    inbound = state["inbound_flight"]
    connections = _bhs.get_connections_for_flight(inbound)

    at_risk = [c for c in connections if c.is_at_risk]
    bag_tags = [c.bag_tag for c in at_risk]

    outbound = ""
    if at_risk:
        outbound = sorted(at_risk, key=lambda c: c.connection_window_minutes)[0].outbound_flight

    return {
        "at_risk_connections": [c.model_dump() for c in at_risk],
        "at_risk_bag_tags": bag_tags,
        "outbound_flight": outbound,
        "actions_taken": [{
            "node": "prepare_context",
            "tool": "bhs",
            "result": f"Found {len(at_risk)} at-risk connections on {inbound}",
        }],
    }


def fetch_departure(state: BaggageCoordinatorState) -> dict[str, Any]:
    """Tier 0 read — departure window remaining on the outbound flight."""
    outbound = state.get("outbound_flight", "")
    if not outbound:
        return {"departure_window_minutes": 0}
    window = _aodb.get_departure_window_minutes(outbound)
    return {
        "departure_window_minutes": window,
        "actions_taken": [{
            "node": "fetch_departure",
            "tool": "aodb",
            "result": f"{outbound} departs in {window} min",
        }],
    }


def fetch_ramp(state: BaggageCoordinatorState) -> dict[str, Any]:
    """Tier 0 read — ramp crew availability and capacity."""
    zone = "B"
    crew = _ramp.get_crew_availability(zone)
    if not crew:
        return {"ramp_crew_available": False, "ramp_zone": zone, "ramp_available_crew": 0}
    return {
        "ramp_crew_available": crew.can_take_exception,
        "ramp_zone": zone,
        "ramp_available_crew": crew.available_crew,
        "actions_taken": [{
            "node": "fetch_ramp",
            "tool": "ramp",
            "result": (
                f"Zone {zone}: {crew.available_crew}/{crew.total_crew} crew, "
                f"can_take={crew.can_take_exception}, "
                f"capacity={simultaneous_capacity(crew.available_crew)} bags"
            ),
        }],
    }


def triage_and_optimize(state: BaggageCoordinatorState) -> dict[str, Any]:
    """Tier 1 + Tier 2 — deterministic triage, CP-SAT if crew is contended.

    Tier 1 (triage_bags): slack = window - move_time per bag.
      slack >= 0 and crew available  →  RECOVERABLE
      slack <  0 or no crew          →  UNRECOVERABLE

    Tier 2 (solve_contended): only invoked when recoverable_count > crew_capacity.
      CP-SAT binary program finds the optimal subset to rush.
      Never invoked for the simple (no-contention) case.
    """
    at_risk = state.get("at_risk_connections", [])
    window = state.get("departure_window_minutes", 0)
    crew_available = state.get("ramp_crew_available", False)
    available_crew = state.get("ramp_available_crew", 0)

    if not at_risk:
        return {
            "feasibility_verdict": FeasibilityVerdict.RECOVERABLE,
            "recoverable_bag_tags": [],
            "unrecoverable_bag_tags": [],
            "feasibility_reasoning": "No at-risk connections — no action needed.",
            "actions_taken": [{"node": "triage_and_optimize",
                               "result": "No at-risk bags — skipped"}],
        }

    # ── Tier 1: deterministic slack triage ───────────────────────────────────
    result = triage_bags(at_risk, window, crew_available)
    recoverable = result.recoverable
    unrecoverable = result.unrecoverable
    reasoning_lines = result.reasoning

    # ── Tier 2: CP-SAT only when there is resource contention ─────────────────
    used_optimizer = False
    if recoverable and has_contention(len(recoverable), available_crew):
        capacity = simultaneous_capacity(available_crew)
        bags_for_opt = []
        from src.tools import store as _store
        for tag in recoverable:
            conn = next((c for c in at_risk if c["bag_tag"] == tag), {})
            slack = window - conn.get("move_time_minutes", 8)
            # Use IATA-aligned priority from the bag's ticket class and FF tier
            bag_obj = _store.BAGS.get(tag)
            priority = bag_obj.priority_weight if bag_obj else 1.0
            bags_for_opt.append(BagForOptimization(
                bag_tag=tag,
                slack_minutes=slack,
                priority_weight=priority,
            ))
        optimal_subset = solve_contended(bags_for_opt, crew_capacity=capacity)
        # Bags not in the optimal subset are deferred to next flight
        deferred = [t for t in recoverable if t not in optimal_subset]
        unrecoverable = unrecoverable + deferred
        recoverable = optimal_subset
        reasoning_lines.append(
            f"Contention: {len(bags_for_opt)} bags, capacity {capacity} — "
            f"CP-SAT selected {len(optimal_subset)}, deferred {len(deferred)}"
        )
        used_optimizer = True

    # Derive verdict
    if not unrecoverable:
        verdict = FeasibilityVerdict.RECOVERABLE
    elif not recoverable:
        verdict = FeasibilityVerdict.UNRECOVERABLE
    else:
        verdict = FeasibilityVerdict.PARTIAL

    summary = (
        f"Tier 1 triage: {len(recoverable)} recoverable, {len(unrecoverable)} unrecoverable "
        f"(window={window}m). {'Tier 2 CP-SAT applied.' if used_optimizer else 'No contention.'}"
    )

    return {
        "feasibility_verdict": verdict,
        "recoverable_bag_tags": recoverable,
        "unrecoverable_bag_tags": unrecoverable,
        "feasibility_reasoning": summary,
        "actions_taken": [{
            "node": "triage_and_optimize",
            "tool": "triage+cpsat" if used_optimizer else "triage",
            "result": summary,
            "reasoning_detail": reasoning_lines,
        }],
    }


def route_bags(state: BaggageCoordinatorState) -> dict[str, Any]:
    """Exception routing, ramp task assignment, and AT_RISK passenger notifications."""
    recoverable = state.get("recoverable_bag_tags", [])
    if not recoverable:
        return {"actions_taken": [{"node": "route_bags", "result": "No recoverable bags — skipped"}]}

    outbound = state.get("outbound_flight", "")
    inbound = state["inbound_flight"]
    zone = state.get("ramp_zone", "B")
    disruption_id = state.get("disruption_id", "")

    ticket = _bhs.open_exception_routing(
        recoverable,
        f"Transfer at risk from {inbound} to {outbound}",
        "",
        disruption_id,
    )

    if outbound:
        _load_plan.add_pending_bags(outbound, recoverable)

    ramp_ticket = _ramp.assign_exception_task(recoverable, inbound, outbound, zone)

    from src.tools import store
    notified = []
    for tag in recoverable:
        bag = store.BAGS.get(tag)
        if bag:
            _notify.notify_bag_at_risk(bag.passenger_id, tag, outbound)
            notified.append(bag.passenger_id)

    return {"actions_taken": [{
        "node": "route_bags",
        "tool": "bhs+ramp+load_plan+passenger_notify",
        "result": (
            f"Exception routing: {len(recoverable)} bags (ticket {ticket.ticket_id}). "
            f"Ramp: {'assigned' if ramp_ticket else 'FAILED — no crew'}. "
            f"{len(notified)} passengers notified (AT_RISK)."
        ),
        "bag_tags": recoverable,
        "bhs_ticket": ticket.ticket_id,
        "ramp_ticket": ramp_ticket.ticket_id if ramp_ticket else None,
        "passengers_notified": notified,
    }]}


def close_loop(state: BaggageCoordinatorState) -> dict[str, Any]:
    """Confirming scan simulation — marks rushed bags as CONFIRMED_LOADED.

    In production: listens for actual BHS scan events confirming bags
    were physically loaded onto the outbound aircraft. Triggers RECOVERED
    passenger notification only when the scan arrives.

    In the demo: simulates immediate confirmation for bags that were rushed
    (they had positive slack, so the ramp crew made it in time).
    """
    recoverable = state.get("recoverable_bag_tags", [])
    outbound = state.get("outbound_flight", "")
    if not recoverable or not outbound:
        return {"actions_taken": [{"node": "close_loop", "result": "No bags to confirm"}]}

    confirmed = []
    notified = []
    from src.tools import store
    for tag in recoverable:
        # Only confirm bags that are in EXCEPTION status (were rushed)
        bag = store.BAGS.get(tag)
        if bag and bag.status.value == "EXCEPTION":
            if _bhs.confirm_bag_loaded(tag, outbound):
                confirmed.append(tag)
                _notify.notify_bag_recovered(bag.passenger_id, tag)
                notified.append(bag.passenger_id)

    return {"actions_taken": [{
        "node": "close_loop",
        "tool": "bhs+passenger_notify",
        "result": (
            f"Confirming scan: {len(confirmed)}/{len(recoverable)} bags confirmed loaded on {outbound}. "
            f"{len(notified)} passengers notified (RECOVERED)."
        ),
        "confirmed_bags": confirmed,
        "passengers_notified": notified,
    }]}


def flag_missed(state: BaggageCoordinatorState) -> dict[str, Any]:
    """Mark unrecoverable bags as missed and notify passengers."""
    unrecoverable = state.get("unrecoverable_bag_tags", [])
    if not unrecoverable:
        return {"actions_taken": [{"node": "flag_missed", "result": "No missed bags — skipped"}]}

    from src.tools import store
    notified = []
    for tag in unrecoverable:
        _bhs.mark_bag_missed(tag)
        bag = store.BAGS.get(tag)
        if bag:
            _notify.notify_bag_missed(bag.passenger_id, tag)
            notified.append(bag.passenger_id)

    return {"actions_taken": [{
        "node": "flag_missed",
        "tool": "bhs+passenger_notify",
        "result": f"Marked {len(unrecoverable)} missed. {len(notified)} passengers notified (MISSED).",
        "bag_tags": unrecoverable,
        "passengers_notified": notified,
    }]}


def _branch(state: BaggageCoordinatorState) -> list[str]:
    verdict = state.get("feasibility_verdict", FeasibilityVerdict.UNRECOVERABLE)
    if verdict == FeasibilityVerdict.RECOVERABLE:
        return ["route_bags"]
    if verdict == FeasibilityVerdict.UNRECOVERABLE:
        return ["flag_missed"]
    return ["route_bags", "flag_missed"]


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_baggage_coordinator() -> StateGraph:
    graph = StateGraph(BaggageCoordinatorState)

    graph.add_node("prepare_context", prepare_context)
    graph.add_node("fetch_departure", fetch_departure)
    graph.add_node("fetch_ramp", fetch_ramp)
    graph.add_node("triage_and_optimize", triage_and_optimize)
    graph.add_node("route_bags", route_bags)
    graph.add_node("close_loop", close_loop)
    graph.add_node("flag_missed", flag_missed)

    graph.add_edge(START, "prepare_context")
    graph.add_edge("prepare_context", "fetch_departure")
    graph.add_edge("prepare_context", "fetch_ramp")
    graph.add_edge("fetch_departure", "triage_and_optimize")
    graph.add_edge("fetch_ramp", "triage_and_optimize")
    graph.add_conditional_edges("triage_and_optimize", _branch)
    # route_bags → close_loop (confirming scan closes the feedback loop)
    graph.add_edge("route_bags", "close_loop")
    graph.add_edge("close_loop", END)
    graph.add_edge("flag_missed", END)

    return graph


baggage_coordinator = build_baggage_coordinator().compile()
