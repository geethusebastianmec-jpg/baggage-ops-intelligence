from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
import uuid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DisruptionType(str, Enum):
    FLIGHT_DELAY = "FLIGHT_DELAY"
    GATE_CHANGE = "GATE_CHANGE"
    CANCELLATION = "CANCELLATION"
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE"
    TRANSFER_AT_RISK = "TRANSFER_AT_RISK"
    COMPOUND = "COMPOUND"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DisruptionEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: DisruptionType
    payload: dict[str, Any]
    severity: Severity = Severity.MEDIUM
    affected_flights: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    source: str = "SYSTEM"


class AgentDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent: str
    disruption_id: str
    reasoning: str
    action: str
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionRecord(BaseModel):
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    decision_id: str
    disruption_id: str
    agent: str
    tool: str
    input: dict[str, Any]
    output: dict[str, Any]
    success: bool
    error: str | None = None
    executed_at: datetime = Field(default_factory=_utcnow)
    duration_ms: int = 0


class CrewStatus(BaseModel):
    zone: str
    available_crew: int
    total_crew: int
    active_tasks: int
    can_take_exception: bool

    @property
    def utilization(self) -> float:
        if self.total_crew == 0:
            return 0.0
        return self.active_tasks / self.total_crew


class TaskTicket(BaseModel):
    ticket_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_type: str
    bag_tags: list[str]
    from_flight: str
    to_flight: str
    assigned_zone: str
    priority: str = "HIGH"
    created_at: datetime = Field(default_factory=_utcnow)
    eta_minutes: int = 5
    completed: bool = False


class FeasibilityVerdict(str, Enum):
    RECOVERABLE = "RECOVERABLE"
    PARTIAL = "PARTIAL"
    UNRECOVERABLE = "UNRECOVERABLE"


class FeasibilityResult(BaseModel):
    verdict: FeasibilityVerdict
    recoverable_bags: list[str]
    unrecoverable_bags: list[str]
    reasoning: str
    recommended_actions: list[str]
