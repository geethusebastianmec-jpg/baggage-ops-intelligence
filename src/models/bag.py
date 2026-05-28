from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field
import uuid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BagStatus(str, Enum):
    CHECKED_IN = "CHECKED_IN"
    IN_TRANSIT = "IN_TRANSIT"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"
    OFFLOADED = "OFFLOADED"
    MISSED = "MISSED"
    RECOVERED = "RECOVERED"


class ExceptionType(str, Enum):
    TRANSFER_AT_RISK = "TRANSFER_AT_RISK"
    TRANSFER_MISSED = "TRANSFER_MISSED"
    DAMAGE = "DAMAGE"
    SECURITY_HOLD = "SECURITY_HOLD"
    WEIGHT_ISSUE = "WEIGHT_ISSUE"


class Bag(BaseModel):
    bag_tag: str
    passenger_id: str
    passenger_name: str
    origin_flight: str
    destination_flight: str | None = None
    final_destination: str = ""
    status: BagStatus = BagStatus.CHECKED_IN
    current_location: str = ""
    weight_kg: float = 20.0
    last_scanned_at: datetime = Field(default_factory=_utcnow)


class TransferConnection(BaseModel):
    connection_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bag_tag: str
    passenger_id: str
    inbound_flight: str
    outbound_flight: str
    connection_window_minutes: int
    minimum_connection_time: int
    is_at_risk: bool = False
    risk_reason: str | None = None

    @property
    def slack_minutes(self) -> int:
        return self.connection_window_minutes - self.minimum_connection_time

    @property
    def is_breached(self) -> bool:
        return self.connection_window_minutes < self.minimum_connection_time


class ExceptionTicket(BaseModel):
    ticket_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bag_tags: list[str]
    exception_type: ExceptionType
    reason: str
    assigned_to: str = "BAGGAGE_SERVICE"
    created_at: datetime = Field(default_factory=_utcnow)
    resolved: bool = False
    resolution: str | None = None


class LoadPlan(BaseModel):
    flight_id: str
    aircraft_type: str
    max_weight_kg: float
    current_weight_kg: float
    bag_count: int
    pending_bags: list[str] = Field(default_factory=list)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    @property
    def available_weight_kg(self) -> float:
        return self.max_weight_kg - self.current_weight_kg
