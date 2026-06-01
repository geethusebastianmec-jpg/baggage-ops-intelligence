"""Playbook registry — fast pattern-match for known disruption types.

No LLM involved. Each playbook specifies which coordinators to activate
and any pre-processing needed to build their input state.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

from src.models import DisruptionEvent, DisruptionType, Severity


@dataclass
class Playbook:
    name: str
    activate: list[str]                              # coordinator names to invoke
    condition: Callable[[DisruptionEvent], bool]     # guard — must match to fire
    severity_threshold: Severity = Severity.LOW      # minimum severity to fire
    build_inputs: Callable[[DisruptionEvent], dict[str, dict[str, Any]]] | None = None


def _delay_inputs(event: DisruptionEvent) -> dict[str, dict[str, Any]]:
    """Build coordinator input dicts from a flight delay event."""
    flight_id = event.payload.get("flight_id", "")
    delay_minutes = event.payload.get("delay_minutes", 0)
    base = {"disruption_id": event.event_id, "actions_taken": []}
    return {
        "baggage_coordinator":  {**base, "inbound_flight": flight_id, "delay_minutes": delay_minutes},
        "interline_coordinator": {**base, "inbound_flight": flight_id, "delay_minutes": delay_minutes},
        "ramp_coordinator":     {**base, "from_flight": flight_id, "bag_tags": [], "to_flight": "", "zone": "B"},
        "dispatch_coordinator": {**base, "flight_id": flight_id, "recoverable_bag_count": 0},
    }


def _gate_change_inputs(event: DisruptionEvent) -> dict[str, dict[str, Any]]:
    base = {"disruption_id": event.event_id, "actions_taken": []}
    return {
        "gate_change_coordinator": {
            **base,
            "flight_id": event.payload.get("flight_id", ""),
            "old_gate": event.payload.get("old_gate", ""),
            "new_gate": event.payload.get("new_gate", ""),
            "old_terminal": event.payload.get("old_terminal", "B"),
            "new_terminal": event.payload.get("new_terminal", "B"),
        },
    }


def _security_hold_inputs(event: DisruptionEvent) -> dict[str, dict[str, Any]]:
    base = {"disruption_id": event.event_id, "actions_taken": []}
    return {
        "security_hold_coordinator": {
            **base,
            "bag_tag": event.payload.get("bag_tag", ""),
            "flight_id": event.payload.get("flight_id", ""),
            "hold_reason": event.payload.get("reason", "Security inspection required"),
            "simulated_outcome": event.payload.get("outcome", "CLEARED"),
        },
    }


def _loading_failure_inputs(event: DisruptionEvent) -> dict[str, dict[str, Any]]:
    base = {"disruption_id": event.event_id, "actions_taken": []}
    return {
        "loading_failure_coordinator": {
            **base,
            "bag_tag": event.payload.get("bag_tag", ""),
            "flight_id": event.payload.get("flight_id", ""),
        },
    }


def _cascade_inputs(event: DisruptionEvent) -> dict[str, dict[str, Any]]:
    """Multiple delayed inbounds → joint optimisation across all their bags."""
    base = {"disruption_id": event.event_id, "actions_taken": []}
    return {
        "network_cascade_coordinator": {
            **base,
            "affected_inbound_flights": event.payload.get("affected_flights",
                                                           event.affected_flights),
        },
    }


def _equipment_failure_inputs(event: DisruptionEvent) -> dict[str, dict[str, Any]]:
    base = {"disruption_id": event.event_id, "actions_taken": []}
    return {
        "equipment_coordinator": {
            **base,
            "equipment_id": event.payload.get("equipment_id", "UNKNOWN"),
            "failed_zone": event.payload.get("zone", "B"),
            "failure_type": event.payload.get("failure_type", "CONVEYOR"),
        },
    }


def _cancellation_inputs(event: DisruptionEvent) -> dict[str, dict[str, Any]]:
    base = {"disruption_id": event.event_id, "actions_taken": []}
    return {
        "cancellation_coordinator": {
            **base,
            "flight_id": event.payload.get("flight_id", ""),
            "reason": event.payload.get("reason", "UNKNOWN"),
        },
    }


PLAYBOOKS: list[Playbook] = [
    Playbook(
        name="FLIGHT_DELAY_STANDARD",
        activate=["baggage_coordinator", "interline_coordinator", "ramp_coordinator"],
        condition=lambda e: (
            e.event_type == DisruptionType.FLIGHT_DELAY
            and e.payload.get("delay_minutes", 0) >= 10
        ),
        severity_threshold=Severity.MEDIUM,
        build_inputs=_delay_inputs,
    ),
    Playbook(
        name="FLIGHT_DELAY_CRITICAL",
        activate=["baggage_coordinator", "interline_coordinator", "ramp_coordinator", "dispatch_coordinator"],
        condition=lambda e: (
            e.event_type == DisruptionType.FLIGHT_DELAY
            and e.payload.get("delay_minutes", 0) >= 30
        ),
        severity_threshold=Severity.HIGH,
        build_inputs=_delay_inputs,
    ),
    Playbook(
        name="GATE_CHANGE",
        activate=["gate_change_coordinator"],
        condition=lambda e: e.event_type == DisruptionType.GATE_CHANGE,
        severity_threshold=Severity.LOW,
        build_inputs=_gate_change_inputs,
    ),
    Playbook(
        name="CANCELLATION",
        activate=["cancellation_coordinator"],
        condition=lambda e: e.event_type == DisruptionType.CANCELLATION,
        severity_threshold=Severity.CRITICAL,
        build_inputs=_cancellation_inputs,
    ),
    Playbook(
        name="SECURITY_HOLD",
        activate=["security_hold_coordinator"],
        condition=lambda e: e.event_type == DisruptionType.SECURITY_HOLD,
        severity_threshold=Severity.HIGH,
        build_inputs=_security_hold_inputs,
    ),
    Playbook(
        name="BAG_NOT_LOADED",
        activate=["loading_failure_coordinator"],
        condition=lambda e: e.event_type == DisruptionType.BAG_NOT_LOADED,
        severity_threshold=Severity.HIGH,
        build_inputs=_loading_failure_inputs,
    ),
    Playbook(
        name="EQUIPMENT_FAILURE",
        activate=["equipment_coordinator"],
        condition=lambda e: e.event_type == DisruptionType.EQUIPMENT_FAILURE,
        severity_threshold=Severity.MEDIUM,
        build_inputs=_equipment_failure_inputs,
    ),
    Playbook(
        name="NETWORK_CASCADE",
        activate=["network_cascade_coordinator"],
        # Fires when a COMPOUND event carries multiple affected flights
        # (hub bank cascades: N inbounds all delayed, same outbound bank at risk)
        condition=lambda e: (
            e.event_type == DisruptionType.COMPOUND
            and len(e.affected_flights) >= 2
        ),
        severity_threshold=Severity.CRITICAL,
        build_inputs=_cascade_inputs,
    ),
]


def match_playbook(event: DisruptionEvent) -> Playbook | None:
    """Return the most specific matching playbook (last match wins — most specific last)."""
    matched = None
    for pb in PLAYBOOKS:
        if pb.condition(event):
            matched = pb
    return matched
