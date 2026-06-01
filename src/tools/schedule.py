"""Schedule mock tool — finds next available flights and handles rebooking.

In production: queries the airline's departure control system (DCS) or
reservation system (GDS). In demo: uses in-memory flight store plus a
simple rule to generate a "next flight" stub.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any

from src.tools import store
from src.tools.base import BaseTool


class ScheduleTool(BaseTool):
    name = "schedule"

    def find_next_flight(
        self, origin: str, destination: str, after_time: datetime | None = None
    ) -> dict[str, Any] | None:
        """Return the next available flight from origin to destination.

        In demo: looks for a flight with matching origin/destination in the store,
        or synthesises a stub if none found.
        """
        self._latency()
        if after_time is None:
            after_time = datetime.now(timezone.utc)

        # Check store for matching flights
        for fid, flight in store.FLIGHTS.items():
            dep = flight.estimated_departure
            if dep.tzinfo is None:
                dep = dep.replace(tzinfo=timezone.utc)
            if (flight.origin == origin and flight.destination == destination
                    and dep > after_time):
                return {
                    "flight_id": fid,
                    "origin": origin,
                    "destination": destination,
                    "estimated_departure": dep.isoformat(),
                    "available_capacity": 10,   # simplified
                }

        # Synthesise a next-day flight if none found (demo stub)
        next_departure = after_time + timedelta(hours=8)
        stub_id = f"AA{origin[:3]}{destination[:3]}NEXT"
        return {
            "flight_id": stub_id,
            "origin": origin,
            "destination": destination,
            "estimated_departure": next_departure.isoformat(),
            "available_capacity": 30,
            "is_stub": True,
        }

    def rebook_bag(
        self, bag_tag: str, original_flight: str, new_flight: str
    ) -> bool:
        """Rebook a bag onto a different flight."""
        self._latency()
        if self._should_fail():
            return False
        bag = store.BAGS.get(bag_tag)
        if not bag:
            return False
        store.BAGS[bag_tag] = bag.model_copy(
            update={"destination_flight": new_flight}
        )
        store.ACTION_LOG.append({
            "tool": self.name,
            "action": "rebook_bag",
            "bag_tag": bag_tag,
            "from_flight": original_flight,
            "to_flight": new_flight,
        })
        return True

    def get_flight_capacity(self, flight_id: str) -> int:
        """Return remaining bag capacity for a flight."""
        self._latency()
        flight = store.FLIGHTS.get(flight_id)
        lp = store.LOAD_PLANS.get(flight_id)
        if not lp:
            return 20  # default
        return max(0, int((lp.max_weight_kg - lp.current_weight_kg) / 20))
