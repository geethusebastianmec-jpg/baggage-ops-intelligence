from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field
import uuid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FlightStatus(str, Enum):
    ON_TIME = "ON_TIME"
    DELAYED = "DELAYED"
    CANCELLED = "CANCELLED"
    DEPARTED = "DEPARTED"
    DIVERTED = "DIVERTED"


class DelayReason(str, Enum):
    WEATHER = "WEATHER"
    CREW = "CREW"
    MECHANICAL = "MECHANICAL"
    ATC = "ATC"
    CONNECTING = "CONNECTING"
    UNKNOWN = "UNKNOWN"


class GateInfo(BaseModel):
    gate_id: str
    terminal: str
    airport: str
    is_available: bool = True


class Flight(BaseModel):
    flight_id: str
    airline: str
    origin: str
    destination: str
    scheduled_departure: datetime
    estimated_departure: datetime
    gate: str
    terminal: str
    status: FlightStatus = FlightStatus.ON_TIME
    aircraft_type: str = "B737"
    capacity: int = 160

    @property
    def delay_minutes(self) -> int:
        delta = self.estimated_departure - self.scheduled_departure
        return max(0, int(delta.total_seconds() / 60))


class DelayEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    flight_id: str
    delay_minutes: int
    reason: DelayReason = DelayReason.UNKNOWN
    detected_at: datetime = Field(default_factory=_utcnow)
    source: str = "ACARS"
    previous_delay_minutes: int = 0


class GateChangeEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    flight_id: str
    old_gate: str
    new_gate: str
    old_terminal: str
    new_terminal: str
    detected_at: datetime = Field(default_factory=_utcnow)


class CancellationEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    flight_id: str
    reason: DelayReason
    detected_at: datetime = Field(default_factory=_utcnow)
    rebooking_flight: str | None = None
