"""Tier 2 — Baggage Domain Coordinator.

LangGraph DAG that handles transfer-risk events:

  START
    └──[prepare_context]          BHS: fetch at-risk connections for inbound flight
           ├──[fetch_departure]   AODB: departure window on outbound (parallel)
           └──[fetch_ramp]        Ramp: crew availability in zone  (parallel)
                   └──[evaluate_feasibility]   LLM: RECOVERABLE / PARTIAL / UNRECOVERABLE
                          ├──[route_bags]       Open exception routing + ramp task
                          └──[flag_missed]      Mark bags missed + passenger notify
                                  └──END
"""
from __future__ import annotations

import json
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END

from src.config import settings
from src.models import FeasibilityVerdict
from src.tier2.state import BaggageCoordinatorState
from src.tools.aodb import AODBTool
from src.tools.bhs import BHSTool
from src.tools.load_plan import LoadPlanTool
from src.tools.passenger_notify import PassengerNotifyTool
from src.tools.ramp import RampTool

# Module-level singletons — re-used across invocations
_bhs = BHSTool()
_aodb = AODBTool()
_ramp = RampTool()
_notify = PassengerNotifyTool()
_load_plan = LoadPlanTool()


# ── Nodes ─────────────────────────────────────────────────────────────────────

def prepare_context(state: BaggageCoordinatorState) -> dict[str, Any]:
    """Query BHS for all at-risk transfer connections on the inbound flight."""
    inbound = state["inbound_flight"]
    connections = _bhs.get_connections_for_flight(inbound)

    at_risk = [c for c in connections if c.is_at_risk]
    bag_tags = [c.bag_tag for c in at_risk]

    # Determine primary outbound flight (most urgent = smallest window)
    outbound = ""
    if at_risk:
        at_risk_sorted = sorted(at_risk, key=lambda c: c.connection_window_minutes)
        outbound = at_risk_sorted[0].outbound_flight

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
    """Query AODB for departure window on the outbound flight."""
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
    """Query ramp tool for crew availability at the inbound gate zone."""
    zone = "B"  # In production: derive from gate assignment via AODB
    crew = _ramp.get_crew_availability(zone)
    if not crew:
        return {"ramp_crew_available": False, "ramp_zone": zone}
    return {
        "ramp_crew_available": crew.can_take_exception,
        "ramp_zone": zone,
        "actions_taken": [{
            "node": "fetch_ramp",
            "tool": "ramp",
            "result": f"Zone {zone}: {crew.available_crew} crew available, can_take={crew.can_take_exception}",
        }],
    }


def evaluate_feasibility(state: BaggageCoordinatorState) -> dict[str, Any]:
    """LLM node — decides RECOVERABLE / PARTIAL / UNRECOVERABLE.

    Takes the three fetched context pieces and reasons about which bags
    can realistically make the connection given the departure window,
    ramp capacity, and number of bags.
    """
    at_risk = state.get("at_risk_connections", [])
    window = state.get("departure_window_minutes", 0)
    ramp_available = state.get("ramp_crew_available", False)
    bag_tags = state.get("at_risk_bag_tags", [])
    inbound = state["inbound_flight"]
    outbound = state.get("outbound_flight", "unknown")

    if not at_risk:
        return {
            "feasibility_verdict": FeasibilityVerdict.RECOVERABLE,
            "recoverable_bag_tags": [],
            "unrecoverable_bag_tags": [],
            "feasibility_reasoning": "No at-risk connections found — no action needed.",
        }

    llm = ChatGoogleGenerativeAI(
        model=settings.llm_tier2,
        google_api_key=settings.google_api_key,
        max_output_tokens=512,
        temperature=0,
    )

    system = SystemMessage(content=(
        "You are a baggage operations intelligence agent. "
        "Given transfer connection data, decide which bags can realistically make "
        "their connecting flight and which cannot. "
        "Respond ONLY with a JSON object matching this schema exactly:\n"
        '{"verdict": "RECOVERABLE"|"PARTIAL"|"UNRECOVERABLE", '
        '"recoverable_bags": [<bag_tags>], '
        '"unrecoverable_bags": [<bag_tags>], '
        '"reasoning": "<one sentence>"}\n'
        "Rules:\n"
        "- RECOVERABLE: all bags can make it with exception handling\n"
        "- PARTIAL: some can, some cannot\n"
        "- UNRECOVERABLE: none can make it\n"
        "- A bag needs at least 8 minutes of ramp work time to transfer\n"
        "- Ramp crew can handle max 3 bags simultaneously per exception task\n"
        "- If ramp crew unavailable, no bags are recoverable"
    ))

    human = HumanMessage(content=(
        f"Inbound flight: {inbound} (delayed)\n"
        f"Outbound flight: {outbound}\n"
        f"Departure window: {window} minutes\n"
        f"Ramp crew available: {ramp_available}\n"
        f"At-risk bags ({len(bag_tags)}): {', '.join(bag_tags)}\n"
        f"Connection details: {json.dumps(at_risk, default=str)}"
    ))

    response = llm.invoke([system, human])
    raw = response.content.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
        verdict = parsed.get("verdict", FeasibilityVerdict.UNRECOVERABLE)
        recoverable = parsed.get("recoverable_bags", [])
        unrecoverable = parsed.get("unrecoverable_bags", [])
        reasoning = parsed.get("reasoning", "")
    except (json.JSONDecodeError, KeyError):
        # Safe fallback: treat as unrecoverable rather than making wrong moves
        verdict = FeasibilityVerdict.UNRECOVERABLE
        recoverable = []
        unrecoverable = bag_tags
        reasoning = f"Feasibility evaluation parse error — defaulting to UNRECOVERABLE. Raw: {raw[:100]}"

    return {
        "feasibility_verdict": verdict,
        "recoverable_bag_tags": recoverable,
        "unrecoverable_bag_tags": unrecoverable,
        "feasibility_reasoning": reasoning,
        "actions_taken": [{
            "node": "evaluate_feasibility",
            "tool": "llm",
            "result": f"Verdict: {verdict} — {reasoning}",
        }],
    }


def route_bags(state: BaggageCoordinatorState) -> dict[str, Any]:
    """Open exception routing for recoverable bags and assign ramp task."""
    recoverable = state.get("recoverable_bag_tags", [])
    if not recoverable:
        return {"actions_taken": [{"node": "route_bags", "result": "No recoverable bags — skipped"}]}

    outbound = state.get("outbound_flight", "")
    inbound = state["inbound_flight"]
    zone = state.get("ramp_zone", "B")
    disruption_id = state.get("disruption_id", "")

    # Open exception routing in BHS
    ticket = _bhs.open_exception_routing(
        recoverable,
        f"Transfer at risk from {inbound} to {outbound}",
        "",
        disruption_id,
    )

    # Flag bags as pending on the load plan
    if outbound:
        _load_plan.add_pending_bags(outbound, recoverable)

    # Assign ramp task
    ramp_ticket = _ramp.assign_exception_task(recoverable, inbound, outbound, zone)

    actions = [{
        "node": "route_bags",
        "tool": "bhs+ramp+load_plan",
        "result": (
            f"Exception routing opened for {len(recoverable)} bags "
            f"(ticket {ticket.ticket_id}). "
            f"Ramp task: {'assigned' if ramp_ticket else 'FAILED — no crew'}."
        ),
        "bag_tags": recoverable,
        "bhs_ticket": ticket.ticket_id,
        "ramp_ticket": ramp_ticket.ticket_id if ramp_ticket else None,
    }]
    return {"actions_taken": actions}


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

    actions = [{
        "node": "flag_missed",
        "tool": "bhs+passenger_notify",
        "result": f"Marked {len(unrecoverable)} bags missed. Notified {len(notified)} passengers.",
        "bag_tags": unrecoverable,
        "passengers_notified": notified,
    }]
    return {"actions_taken": actions}


def _branch_after_evaluation(state: BaggageCoordinatorState) -> list[str]:
    verdict = state.get("feasibility_verdict", FeasibilityVerdict.UNRECOVERABLE)
    if verdict == FeasibilityVerdict.RECOVERABLE:
        return ["route_bags"]
    if verdict == FeasibilityVerdict.UNRECOVERABLE:
        return ["flag_missed"]
    # PARTIAL — do both
    return ["route_bags", "flag_missed"]


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_baggage_coordinator() -> StateGraph:
    graph = StateGraph(BaggageCoordinatorState)

    graph.add_node("prepare_context", prepare_context)
    graph.add_node("fetch_departure", fetch_departure)
    graph.add_node("fetch_ramp", fetch_ramp)
    graph.add_node("evaluate_feasibility", evaluate_feasibility)
    graph.add_node("route_bags", route_bags)
    graph.add_node("flag_missed", flag_missed)

    # Linear → parallel fan-out → converge → conditional branch
    graph.add_edge(START, "prepare_context")
    graph.add_edge("prepare_context", "fetch_departure")
    graph.add_edge("prepare_context", "fetch_ramp")
    graph.add_edge("fetch_departure", "evaluate_feasibility")
    graph.add_edge("fetch_ramp", "evaluate_feasibility")
    graph.add_conditional_edges("evaluate_feasibility", _branch_after_evaluation)
    graph.add_edge("route_bags", END)
    graph.add_edge("flag_missed", END)

    return graph


# Compiled graph — import this in other modules
baggage_coordinator = build_baggage_coordinator().compile()
