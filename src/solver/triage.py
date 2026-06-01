"""Tier 1 — deterministic bag triage.

Answers the question: "can this bag physically make the connection?"
using pure arithmetic. No LLM, no randomness. Same inputs → same output.

Formula per bag:
    slack = departure_window_minutes - bag.move_time_minutes
    slack >= 0 AND crew available  →  RECOVERABLE
    slack <  0 OR  no crew         →  UNRECOVERABLE

move_time_minutes is the physical ramp-crew transfer time based on BHS zone:
    Zone B (near gate)     ~8 min   — bag is close, easy sprint
    Zone C (mid terminal)  ~12 min  — moderate distance
    Zone D (far queue)     ~26 min  — bag is deep in the BHS queue
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TriageResult:
    recoverable: list[str]       # bag_tags that CAN make the connection
    unrecoverable: list[str]     # bag_tags that CANNOT (physically impossible)
    reasoning: list[str] = field(default_factory=list)   # per-bag explanation for audit log


def triage_bags(
    connections: list[dict[str, Any]],
    departure_window_minutes: int,
    crew_available: bool,
) -> TriageResult:
    """Pure arithmetic triage — O(n) in number of bags."""
    recoverable: list[str] = []
    unrecoverable: list[str] = []
    reasoning: list[str] = []

    for conn in connections:
        tag = conn["bag_tag"]
        move_time = conn.get("move_time_minutes", 8)
        slack = departure_window_minutes - move_time

        if not crew_available:
            unrecoverable.append(tag)
            reasoning.append(
                f"{tag}: no crew available → UNRECOVERABLE"
            )
        elif slack >= 0:
            recoverable.append(tag)
            reasoning.append(
                f"{tag}: window={departure_window_minutes}m move={move_time}m "
                f"slack=+{slack}m → RECOVERABLE"
            )
        else:
            unrecoverable.append(tag)
            reasoning.append(
                f"{tag}: window={departure_window_minutes}m move={move_time}m "
                f"slack={slack}m → UNRECOVERABLE (physically impossible)"
            )

    return TriageResult(
        recoverable=recoverable,
        unrecoverable=unrecoverable,
        reasoning=reasoning,
    )


def simultaneous_capacity(available_crew: int, bags_per_crew: int = 3) -> int:
    """Max bags that can be physically moved at the same time."""
    return available_crew * bags_per_crew


def has_contention(recoverable_count: int, available_crew: int, bags_per_crew: int = 3) -> bool:
    """True when more bags need rushing than crew can handle simultaneously."""
    return recoverable_count > simultaneous_capacity(available_crew, bags_per_crew)
