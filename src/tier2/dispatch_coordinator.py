"""Tier 2 — Dispatch Domain Coordinator.

Decides whether to hold a departure or let it go.

  START → [fetch_load_plan ‖ fetch_departure_window] → decide_hold → END

Hold policy:
  - recoverable_bag_count >= 1  AND  departure_window > 5 min  → HOLD
  - departure_window <= 5 min                                  → DEPART
  - recoverable_bag_count == 0                                 → DEPART
  - ambiguous (>8 bags, window 6-10 min)                       → ESCALATE
"""
from __future__ import annotations
from typing import Any
import json

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END

from src.config import settings
from src.tier2.state import DispatchCoordinatorState
from src.tools.aodb import AODBTool
from src.tools.load_plan import LoadPlanTool

_aodb = AODBTool()
_load_plan = LoadPlanTool()


def fetch_load_plan(state: DispatchCoordinatorState) -> dict[str, Any]:
    flight_id = state["flight_id"]
    lp = _load_plan.get_load_plan(flight_id)
    return {
        "load_plan": lp.model_dump() if lp else None,
        "actions_taken": [{"node": "fetch_load_plan", "tool": "load_plan",
                           "result": f"{flight_id}: {lp.bag_count} bags, {len(lp.pending_bags)} pending" if lp else "No load plan"}],
    }


def fetch_departure_window(state: DispatchCoordinatorState) -> dict[str, Any]:
    flight_id = state["flight_id"]
    window = _aodb.get_departure_window_minutes(flight_id)
    return {
        "departure_window_minutes": window,
        "actions_taken": [{"node": "fetch_departure_window", "tool": "aodb",
                           "result": f"{flight_id} departs in {window} min"}],
    }


def decide_hold(state: DispatchCoordinatorState) -> dict[str, Any]:
    recoverable = state.get("recoverable_bag_count", 0)
    window = state.get("departure_window_minutes", 0)
    lp = state.get("load_plan")
    pending = len(lp.get("pending_bags", [])) if lp else 0

    # Rule-based fast paths — no LLM needed
    if window <= 5:
        return _decision("DEPART", f"Departure window only {window} min — too late to hold.", state)
    if recoverable == 0 and pending == 0:
        return _decision("DEPART", "No recoverable bags pending — no reason to hold.", state)
    if recoverable <= 3 and window >= 10:
        return _decision("HOLD", f"{recoverable} bag(s) recoverable with {window} min remaining — hold approved.", state)

    # Ambiguous: use LLM
    llm = ChatGoogleGenerativeAI(model=settings.llm_tier2, google_api_key=settings.google_api_key,
                                 max_output_tokens=256, temperature=0)
    system = SystemMessage(content=(
        "You are a departure control agent. Decide: HOLD, DEPART, or ESCALATE.\n"
        "Respond ONLY with JSON: {\"decision\": \"HOLD\"|\"DEPART\"|\"ESCALATE\", \"reasoning\": \"<one sentence>\"}"
    ))
    human = HumanMessage(content=(
        f"Flight: {state['flight_id']}\nDeparture window: {window} min\n"
        f"Recoverable bags pending: {recoverable}\nLoad plan pending bags: {pending}"
    ))
    response = llm.invoke([system, human])
    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    try:
        parsed = json.loads(raw)
        decision = parsed.get("decision", "ESCALATE")
        reasoning = parsed.get("reasoning", "")
    except json.JSONDecodeError:
        decision, reasoning = "ESCALATE", f"Parse error: {raw[:80]}"

    return _decision(decision, reasoning, state)


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
