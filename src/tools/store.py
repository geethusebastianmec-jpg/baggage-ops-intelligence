"""In-memory data store shared by all mock tools.

Populated by demo/seed_data.py at demo startup.
All tools read/write against this store.
"""
from src.models import Bag, Flight, LoadPlan, TransferConnection, CrewStatus
from src.solver.rerouter import FlightLeg

# Keyed by flight_id
FLIGHTS: dict[str, Flight] = {}

# Keyed by bag_tag
BAGS: dict[str, Bag] = {}

# Keyed by bag_tag → list of connections (a bag may have multiple legs)
CONNECTIONS: dict[str, list[TransferConnection]] = {}

# Keyed by flight_id
LOAD_PLANS: dict[str, LoadPlan] = {}

# Keyed by zone (e.g. "B", "C")
CREW_STATUS: dict[str, CrewStatus] = {}

# Available rerouting flights — used by the MIP rerouter for missed bags.
# Populated by seed_data.py; each FlightLeg carries remaining bag capacity.
REROUTING_FLIGHTS: list[FlightLeg] = []

# Immutable audit log appended by every tool call
ACTION_LOG: list[dict] = []


def reset() -> None:
    """Clear all state — used between test runs."""
    FLIGHTS.clear()
    BAGS.clear()
    CONNECTIONS.clear()
    LOAD_PLANS.clear()
    CREW_STATUS.clear()
    REROUTING_FLIGHTS.clear()
    ACTION_LOG.clear()
