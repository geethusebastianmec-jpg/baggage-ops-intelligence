"""Shared state schemas for all Tier 2 domain coordinators."""
import operator
from typing import Annotated, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class BaggageCoordinatorState(TypedDict, total=False):
    # ── Input (required) ─────────────────────────────────────────────────────
    disruption_id: str
    inbound_flight: str
    delay_minutes: int

    # ── Set by prepare_context node ───────────────────────────────────────────
    # List of TransferConnection dicts from BHS
    at_risk_connections: list[dict[str, Any]]
    # Primary outbound flight affected (first/most urgent)
    outbound_flight: str
    # All bag_tags at risk
    at_risk_bag_tags: list[str]

    # ── Set by parallel fetch nodes ───────────────────────────────────────────
    departure_window_minutes: int    # minutes until outbound departs
    ramp_crew_available: bool        # True if crew can take exception task
    ramp_zone: str                   # zone identifier for ramp crew

    # ── Set by evaluate_feasibility node (LLM) ────────────────────────────────
    feasibility_verdict: str         # RECOVERABLE | PARTIAL | UNRECOVERABLE
    recoverable_bag_tags: list[str]
    unrecoverable_bag_tags: list[str]
    feasibility_reasoning: str

    # ── Accumulated by action nodes ───────────────────────────────────────────
    actions_taken: Annotated[list[dict[str, Any]], operator.add]

    # ── Error tracking ────────────────────────────────────────────────────────
    error: str | None


class RampCoordinatorState(TypedDict, total=False):
    disruption_id: str
    bag_tags: list[str]
    from_flight: str
    to_flight: str
    zone: str
    task_ticket: dict[str, Any] | None
    actions_taken: Annotated[list[dict[str, Any]], operator.add]
    error: str | None


class DispatchCoordinatorState(TypedDict, total=False):
    disruption_id: str
    flight_id: str
    pending_bag_count: int
    recoverable_bag_count: int
    departure_window_minutes: int
    load_plan: dict[str, Any] | None
    hold_decision: str | None          # HOLD | DEPART | ESCALATE
    hold_reasoning: str
    actions_taken: Annotated[list[dict[str, Any]], operator.add]
    error: str | None


class CommsCoordinatorState(TypedDict, total=False):
    disruption_id: str
    notifications: list[dict[str, Any]]   # [{passenger_id, bag_tag, type}]
    sent_count: int
    failed_count: int
    actions_taken: Annotated[list[dict[str, Any]], operator.add]
    error: str | None
