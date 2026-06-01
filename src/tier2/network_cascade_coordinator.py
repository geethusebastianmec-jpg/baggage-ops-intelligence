"""Tier 2 — Network Cascade Coordinator.

Triggered when multiple inbound delays hit the same outbound bank simultaneously.
The critical difference from running separate delay workflows: those workflows each
think they have full crew capacity. In a cascade, they compete for the same ramp
crew. A single joint CP-SAT run sees all bags at once and finds the optimal
allocation under the true shared constraint.

  START
    └──[aggregate_cascade]    Collect all at-risk bags across all affected inbounds
           └──[joint_triage]  Tier 1: slack math per bag with true crew capacity
                  └──[joint_optimize]  Tier 2: single CP-SAT across all bags
                         └──[dispatch_all]  Tier 1: issue all actions at once
                                └──END
"""
from __future__ import annotations
from typing import Any, Annotated
import operator

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from src.models import BagStatus
from src.solver.triage import triage_bags, has_contention, simultaneous_capacity
from src.solver.optimizer import solve_contended, BagForOptimization
from src.tools.aodb import AODBTool
from src.tools.bhs import BHSTool
from src.tools.ramp import RampTool
from src.tools.load_plan import LoadPlanTool
from src.tools.passenger_notify import PassengerNotifyTool
from src.tools import store

_bhs = BHSTool()
_aodb = AODBTool()
_ramp = RampTool()
_load_plan = LoadPlanTool()
_notify = PassengerNotifyTool()


class NetworkCascadeCoordinatorState(TypedDict, total=False):
    disruption_id: str
    affected_inbound_flights: list[str]    # multiple delayed inbounds
    # Set by aggregate_cascade
    all_at_risk_connections: list[dict[str, Any]]
    outbound_flights: list[str]            # unique outbounds at risk
    # Set by joint_triage
    triaged_recoverable: list[str]         # bag_tags with positive slack
    triaged_unrecoverable: list[str]       # bag_tags that cannot make it
    total_crew_capacity: int
    # Set by joint_optimize
    joint_recoverable: list[str]           # CP-SAT selected subset to rush
    joint_unrecoverable: list[str]         # remaining (capacity or slack limited)
    # Actions
    actions_taken: Annotated[list[dict[str, Any]], operator.add]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def aggregate_cascade(state: NetworkCascadeCoordinatorState) -> dict[str, Any]:
    """Collect all at-risk connections across every delayed inbound in the cascade."""
    inbounds = state.get("affected_inbound_flights", [])
    all_connections = []
    outbounds = set()

    for inbound in inbounds:
        for conns in store.CONNECTIONS.values():
            for conn in conns:
                if conn.inbound_flight == inbound and conn.is_at_risk:
                    all_connections.append(conn.model_dump())
                    outbounds.add(conn.outbound_flight)

    return {
        "all_at_risk_connections": all_connections,
        "outbound_flights": list(outbounds),
        "actions_taken": [{
            "node": "aggregate_cascade",
            "tool": "bhs",
            "result": (
                f"Cascade: {len(inbounds)} inbounds, {len(all_connections)} total at-risk bags, "
                f"{len(outbounds)} outbound flights affected."
            ),
            "inbound_flights": inbounds,
            "outbound_flights": list(outbounds),
        }],
    }


def joint_triage(state: NetworkCascadeCoordinatorState) -> dict[str, Any]:
    """Tier 1 — per-bag slack triage across all cascade bags.

    Each bag gets its departure window from its specific outbound flight.
    Crew capacity is the TOTAL available across all zones (shared resource).
    """
    all_connections = state.get("all_at_risk_connections", [])

    # Get the true departure windows per outbound
    windows: dict[str, int] = {}
    for outbound in state.get("outbound_flights", []):
        windows[outbound] = _aodb.get_departure_window_minutes(outbound)

    # Get total crew capacity across all ramp zones
    total_capacity = sum(
        simultaneous_capacity(crew.available_crew)
        for crew in store.CREW_STATUS.values()
        if crew.can_take_exception
    )

    recoverable: list[str] = []
    unrecoverable: list[str] = []
    reasoning: list[str] = []

    for conn in all_connections:
        tag = conn["bag_tag"]
        outbound = conn.get("outbound_flight", "")
        window = windows.get(outbound, 0)
        move_time = conn.get("move_time_minutes", 8)
        slack = window - move_time

        if slack >= 0:
            recoverable.append(tag)
            reasoning.append(f"{tag}: slack=+{slack}m → triage RECOVERABLE")
        else:
            unrecoverable.append(tag)
            reasoning.append(f"{tag}: slack={slack}m → triage UNRECOVERABLE")

    return {
        "triaged_recoverable": recoverable,
        "triaged_unrecoverable": unrecoverable,
        "total_crew_capacity": total_capacity,
        "actions_taken": [{
            "node": "joint_triage",
            "tool": "triage",
            "result": (
                f"Joint triage: {len(recoverable)} recoverable, {len(unrecoverable)} unrecoverable. "
                f"Total crew capacity: {total_capacity} bags."
            ),
        }],
    }


def joint_optimize(state: NetworkCascadeCoordinatorState) -> dict[str, Any]:
    """Tier 2 — single CP-SAT run across all cascade bags under shared crew constraint.

    This is the key difference from running separate per-inbound delay workflows:
    a single optimiser sees all competing bags and the true shared crew capacity,
    producing one coherent plan rather than N independent plans that overpromise.
    """
    recoverable = state.get("triaged_recoverable", [])
    unrecoverable = list(state.get("triaged_unrecoverable", []))
    capacity = state.get("total_crew_capacity", 0)

    if not recoverable:
        return {
            "joint_recoverable": [],
            "joint_unrecoverable": unrecoverable,
            "actions_taken": [{"node": "joint_optimize", "result": "No recoverable bags to optimise"}],
        }

    if not has_contention(len(recoverable), 0, 0) or len(recoverable) <= capacity:
        # No contention — all recoverable bags can be rushed
        return {
            "joint_recoverable": recoverable,
            "joint_unrecoverable": unrecoverable,
            "actions_taken": [{
                "node": "joint_optimize", "tool": "triage",
                "result": f"No contention: all {len(recoverable)} recoverable bags will be rushed.",
            }],
        }

    # Run the joint CP-SAT
    all_connections = state.get("all_at_risk_connections", [])
    windows: dict[str, int] = {}
    for outbound in state.get("outbound_flights", []):
        windows[outbound] = _aodb.get_departure_window_minutes(outbound)

    bags_for_opt = []
    for tag in recoverable:
        conn = next((c for c in all_connections if c["bag_tag"] == tag), {})
        outbound = conn.get("outbound_flight", "")
        window = windows.get(outbound, 0)
        move_time = conn.get("move_time_minutes", 8)
        slack = window - move_time
        bags_for_opt.append(BagForOptimization(bag_tag=tag, slack_minutes=max(0, slack)))

    optimal = solve_contended(bags_for_opt, crew_capacity=capacity)
    deferred = [t for t in recoverable if t not in optimal]

    return {
        "joint_recoverable": optimal,
        "joint_unrecoverable": unrecoverable + deferred,
        "actions_taken": [{
            "node": "joint_optimize",
            "tool": "cpsat",
            "result": (
                f"Joint CP-SAT: {len(recoverable)} candidates, capacity {capacity}. "
                f"Selected {len(optimal)} to rush, deferred {len(deferred)}."
            ),
        }],
    }


def dispatch_all(state: NetworkCascadeCoordinatorState) -> dict[str, Any]:
    """Tier 1 — dispatch all actions for the joint plan."""
    to_rush = state.get("joint_recoverable", [])
    to_miss = state.get("joint_unrecoverable", [])
    disruption_id = state.get("disruption_id", "")
    all_connections = state.get("all_at_risk_connections", [])

    # Group bags by outbound flight for efficient dispatching
    outbound_map: dict[str, list[str]] = {}
    for tag in to_rush:
        conn = next((c for c in all_connections if c["bag_tag"] == tag), {})
        outbound = conn.get("outbound_flight", "")
        outbound_map.setdefault(outbound, []).append(tag)

    tickets = []
    for outbound, bag_tags in outbound_map.items():
        ticket = _bhs.open_exception_routing(bag_tags, f"Cascade recovery → {outbound}", "", disruption_id)
        tickets.append(ticket.ticket_id)
        _load_plan.add_pending_bags(outbound, bag_tags)
        # Assign to available crew zone
        for zone, crew in store.CREW_STATUS.items():
            if crew.can_take_exception:
                _ramp.assign_exception_task(bag_tags, "CASCADE", outbound, zone)
                break
        for tag in bag_tags:
            bag = store.BAGS.get(tag)
            if bag:
                _notify.notify_bag_at_risk(bag.passenger_id, tag, outbound)

    for tag in to_miss:
        _bhs.mark_bag_missed(tag)
        bag = store.BAGS.get(tag)
        if bag:
            _notify.notify_bag_missed(bag.passenger_id, tag)

    return {"actions_taken": [{
        "node": "dispatch_all",
        "tool": "bhs+ramp+load_plan+passenger_notify",
        "result": (
            f"Dispatched: {len(to_rush)} bags rushed across {len(outbound_map)} outbounds. "
            f"{len(to_miss)} bags missed. {len(tickets)} exception tickets."
        ),
        "rushed_bags": to_rush,
        "missed_bags": to_miss,
    }]}


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_network_cascade_coordinator() -> StateGraph:
    graph = StateGraph(NetworkCascadeCoordinatorState)

    graph.add_node("aggregate_cascade", aggregate_cascade)
    graph.add_node("joint_triage", joint_triage)
    graph.add_node("joint_optimize", joint_optimize)
    graph.add_node("dispatch_all", dispatch_all)

    graph.add_edge(START, "aggregate_cascade")
    graph.add_edge("aggregate_cascade", "joint_triage")
    graph.add_edge("joint_triage", "joint_optimize")
    graph.add_edge("joint_optimize", "dispatch_all")
    graph.add_edge("dispatch_all", END)

    return graph


network_cascade_coordinator = build_network_cascade_coordinator().compile()
