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
    CONFIRMED_LOADED = "CONFIRMED_LOADED"   # confirming scan received — bag physically on aircraft
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


class TicketClass(str, Enum):
    CREW     = "CREW"       # Deadheading / positioning crew — IATA Priority 1
    FIRST    = "FIRST"      # First class — IATA Priority 2
    BUSINESS = "BUSINESS"   # Business class — IATA Priority 2
    ECONOMY  = "ECONOMY"    # Economy — IATA Priority 3


class FrequentFlyerTier(str, Enum):
    NONE     = "NONE"
    SILVER   = "SILVER"
    GOLD     = "GOLD"
    PLATINUM = "PLATINUM"


# IATA-aligned priority weights used by CP-SAT (T2a) and MIP rerouter (T2b).
# Crew bags have the highest priority in IATA standard; within Economy,
# frequent flyer tier adds a small lift.
PRIORITY_WEIGHTS: dict[tuple[str, str], float] = {
    (TicketClass.CREW,     FrequentFlyerTier.NONE):     3.0,
    (TicketClass.FIRST,    FrequentFlyerTier.PLATINUM):  2.8,
    (TicketClass.FIRST,    FrequentFlyerTier.GOLD):      2.6,
    (TicketClass.FIRST,    FrequentFlyerTier.SILVER):    2.5,
    (TicketClass.FIRST,    FrequentFlyerTier.NONE):      2.4,
    (TicketClass.BUSINESS, FrequentFlyerTier.PLATINUM):  2.2,
    (TicketClass.BUSINESS, FrequentFlyerTier.GOLD):      2.1,
    (TicketClass.BUSINESS, FrequentFlyerTier.SILVER):    2.0,
    (TicketClass.BUSINESS, FrequentFlyerTier.NONE):      1.9,
    (TicketClass.ECONOMY,  FrequentFlyerTier.PLATINUM):  1.5,
    (TicketClass.ECONOMY,  FrequentFlyerTier.GOLD):      1.3,
    (TicketClass.ECONOMY,  FrequentFlyerTier.SILVER):    1.2,
    (TicketClass.ECONOMY,  FrequentFlyerTier.NONE):      1.0,
}


def bag_priority_weight(ticket_class: str, ff_tier: str) -> float:
    """Return the IATA-aligned numeric priority weight for CP-SAT / MIP."""
    return PRIORITY_WEIGHTS.get((ticket_class, ff_tier), 1.0)


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
    # Passenger profile — drives IATA priority in CP-SAT and MIP
    ticket_class: TicketClass = TicketClass.ECONOMY
    frequent_flyer_tier: FrequentFlyerTier = FrequentFlyerTier.NONE

    @property
    def priority_weight(self) -> float:
        return bag_priority_weight(self.ticket_class, self.frequent_flyer_tier)


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
    # Interline: bag is transferring between two different airlines.
    # The system has no direct control over the receiving airline's BHS.
    # Interline bags trigger the InterlineCoordinator workflow instead of
    # the standard BaggageCoordinator, and are flagged for manual oversight
    # even when slack is positive (no guaranteed automated handoff).
    is_interline: bool = False
    partner_airline: str | None = None   # IATA 2-letter code, e.g. "LH", "UA"

    # Physical time (minutes) for ramp crew to move this bag from its current
    # BHS zone to the outbound aircraft hold. Varies by airport zone:
    #   Zone B (near gate):   ~8 min
    #   Zone C (mid terminal): ~12 min
    #   Zone D (far queue):   ~26 min
    move_time_minutes: int = 8

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
