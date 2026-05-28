"""Tier 1 — Strategic Supervisor.

Two operating modes:

  Playbook mode (fast path, ~80% of events):
    Matches DisruptionEvent to a Playbook, builds coordinator inputs,
    invokes coordinators in parallel threads, collects results.

  ReAct mode (novel/compound events, ~20%):
    Invoked when no playbook matches or multiple simultaneous disruptions
    require cross-domain reasoning. Uses Claude Opus via LangGraph ReAct.

  Conflict resolution:
    When domain coordinator results contain conflicting decisions
    (e.g. Baggage wants to HOLD, Dispatch decided to DEPART),
    the supervisor arbitrates using the cost model.
"""
from __future__ import annotations

import concurrent.futures
import json
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage

from src.config import settings
from src.models import DisruptionEvent, DisruptionType, Severity
from src.tier1.playbooks import match_playbook
from src.tier2.baggage_coordinator import build_baggage_coordinator
from src.tier2.ramp_coordinator import build_ramp_coordinator
from src.tier2.dispatch_coordinator import build_dispatch_coordinator
from src.tier2.comms_coordinator import build_comms_coordinator

_COORDINATOR_BUILDERS = {
    "baggage_coordinator": build_baggage_coordinator,
    "ramp_coordinator": build_ramp_coordinator,
    "dispatch_coordinator": build_dispatch_coordinator,
    "comms_coordinator": build_comms_coordinator,
}

_CONFLICT_PAIRS = {
    ("baggage_coordinator", "dispatch_coordinator"): ("hold_decision", "HOLD", "DEPART"),
}


class StrategicSupervisor:
    """Stateless supervisor — one instance can process many events."""

    def process(self, event: DisruptionEvent) -> dict[str, Any]:
        """Main entry point. Returns a summary of all actions taken."""
        playbook = match_playbook(event)

        if playbook:
            return self._run_playbook(event, playbook)
        return self._run_react(event)

    # ── Playbook path ─────────────────────────────────────────────────────────

    def _run_playbook(self, event: DisruptionEvent, playbook) -> dict[str, Any]:
        coordinator_inputs = playbook.build_inputs(event) if playbook.build_inputs else {}

        results: dict[str, dict] = {}
        errors: dict[str, str] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self._invoke_coordinator, name, coordinator_inputs.get(name, {})):
                name for name in playbook.activate
            }
            for future, name in futures.items():
                try:
                    results[name] = future.result(timeout=60)
                except Exception as exc:
                    errors[name] = str(exc)

        conflicts = self._detect_conflicts(results)
        if conflicts:
            resolution = self._arbitrate(event, results, conflicts)
            results["conflict_resolution"] = resolution

        all_actions = []
        for name, result in results.items():
            for action in result.get("actions_taken", []):
                all_actions.append({**action, "coordinator": name})

        return {
            "disruption_id": event.event_id,
            "playbook": playbook.name,
            "coordinators_activated": playbook.activate,
            "coordinator_results": results,
            "all_actions": all_actions,
            "errors": errors,
            "mode": "PLAYBOOK",
        }

    def _invoke_coordinator(self, name: str, input_state: dict[str, Any]) -> dict[str, Any]:
        builder = _COORDINATOR_BUILDERS.get(name)
        if not builder:
            raise ValueError(f"Unknown coordinator: {name}")
        graph = builder().compile()
        return graph.invoke(input_state)

    # ── Conflict resolution ───────────────────────────────────────────────────

    def _detect_conflicts(self, results: dict[str, dict]) -> list[tuple[str, str]]:
        conflicts = []
        for (a, b), (field, val_a, val_b) in _CONFLICT_PAIRS.items():
            if a in results and b in results:
                result_a = results[a].get(field)
                result_b = results[b].get(field)
                if result_a == val_a and result_b == val_b:
                    conflicts.append((a, b))
        return conflicts

    def _arbitrate(
        self, event: DisruptionEvent, results: dict[str, dict], conflicts: list[tuple[str, str]]
    ) -> dict[str, Any]:
        """Use Claude Opus to resolve conflicts between domain coordinators."""
        llm = ChatAnthropic(
            model=settings.llm_tier1_novel,
            api_key=settings.anthropic_api_key,
            max_tokens=512,
            temperature=0,
        )
        conflict_summary = []
        for a, b in conflicts:
            conflict_summary.append(
                f"{a} says HOLD; {b} says DEPART. "
                f"Baggage reasoning: {results.get(a, {}).get('feasibility_reasoning', 'N/A')}. "
                f"Dispatch reasoning: {results.get(b, {}).get('hold_reasoning', 'N/A')}."
            )

        system = SystemMessage(content=(
            "You are the Operations Intelligence Layer. Resolve a conflict between domain agents. "
            "Cost model: each delayed departure minute costs ~$500. Each mishandled bag costs ~$150 "
            "plus customer relations damage. Network cascade risk if hub departure is held >10 min. "
            "Respond ONLY with JSON: "
            "{\"resolution\": \"HOLD\"|\"DEPART\", \"reasoning\": \"<one sentence>\", "
            "\"winning_agent\": \"baggage_coordinator\"|\"dispatch_coordinator\"}"
        ))
        human = HumanMessage(content="\n".join(conflict_summary))

        response = llm.invoke([system, human])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"resolution": "ESCALATE", "reasoning": f"Parse error: {raw[:80]}", "winning_agent": "none"}

    # ── ReAct path ────────────────────────────────────────────────────────────

    def _run_react(self, event: DisruptionEvent) -> dict[str, Any]:
        """Novel or compound disruption — reason with Claude Opus then dispatch."""
        llm = ChatAnthropic(
            model=settings.llm_tier1_novel,
            api_key=settings.anthropic_api_key,
            max_tokens=1024,
            temperature=0,
        )
        available = list(_COORDINATOR_BUILDERS.keys())
        system = SystemMessage(content=(
            "You are the Operations Intelligence Layer for an airline hub. "
            "Given a disruption event, decide which domain coordinators to activate and why. "
            f"Available coordinators: {available}. "
            "Respond ONLY with JSON: "
            "{\"activate\": [<coordinator_names>], \"reasoning\": \"<one sentence>\"}"
        ))
        human = HumanMessage(content=(
            f"Event type: {event.event_type}\n"
            f"Severity: {event.severity}\n"
            f"Affected flights: {event.affected_flights}\n"
            f"Payload: {json.dumps(event.payload)}"
        ))

        response = llm.invoke([system, human])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()

        try:
            parsed = json.loads(raw)
            to_activate = [c for c in parsed.get("activate", []) if c in _COORDINATOR_BUILDERS]
            reasoning = parsed.get("reasoning", "")
        except json.JSONDecodeError:
            to_activate = list(_COORDINATOR_BUILDERS.keys())
            reasoning = "Fallback: activating all coordinators due to parse error"

        base_input = {"disruption_id": event.event_id, "actions_taken": []}
        results, errors = {}, {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self._invoke_coordinator, name, {
                    **base_input,
                    "inbound_flight": event.payload.get("flight_id", ""),
                    "delay_minutes": event.payload.get("delay_minutes", 0),
                    "flight_id": event.payload.get("flight_id", ""),
                    "notifications": [],
                    "bag_tags": [],
                    "from_flight": event.payload.get("flight_id", ""),
                    "to_flight": "",
                    "zone": "B",
                    "recoverable_bag_count": 0,
                }): name
                for name in to_activate
            }
            for future, name in futures.items():
                try:
                    results[name] = future.result(timeout=60)
                except Exception as exc:
                    errors[name] = str(exc)

        all_actions = []
        for name, result in results.items():
            for action in result.get("actions_taken", []):
                all_actions.append({**action, "coordinator": name})

        return {
            "disruption_id": event.event_id,
            "react_reasoning": reasoning,
            "coordinators_activated": to_activate,
            "coordinator_results": results,
            "all_actions": all_actions,
            "errors": errors,
            "mode": "REACT",
        }


# Module-level singleton
supervisor = StrategicSupervisor()
