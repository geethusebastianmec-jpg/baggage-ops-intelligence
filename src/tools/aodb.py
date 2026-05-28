"""Airport Operations Database mock tool.

Covers: flight status, gate info, departure window calculations.
"""
from datetime import datetime, timezone

from src.models import Flight, FlightStatus, GateInfo
from src.tools import store
from src.tools.base import BaseTool


class AODBTool(BaseTool):
    name = "aodb"

    def get_flight(self, flight_id: str) -> Flight | None:
        self._latency()
        return store.FLIGHTS.get(flight_id)

    def get_departure_window_minutes(self, flight_id: str) -> int:
        """Minutes remaining until hard departure (estimated_departure)."""
        self._latency()
        flight = store.FLIGHTS.get(flight_id)
        if not flight:
            return 0
        now = datetime.now(timezone.utc)
        # Handle naive datetimes in seed data gracefully
        dep = flight.estimated_departure
        if dep.tzinfo is None:
            dep = dep.replace(tzinfo=timezone.utc)
        delta = (dep - now).total_seconds() / 60
        return max(0, int(delta))

    def get_gate_info(self, flight_id: str) -> GateInfo | None:
        self._latency()
        flight = store.FLIGHTS.get(flight_id)
        if not flight:
            return None
        return GateInfo(
            gate_id=flight.gate,
            terminal=flight.terminal,
            airport=flight.destination,
        )

    def update_flight_status(self, flight_id: str, status: FlightStatus) -> bool:
        self._latency()
        flight = store.FLIGHTS.get(flight_id)
        if not flight:
            return False
        store.FLIGHTS[flight_id] = flight.model_copy(update={"status": status})
        store.ACTION_LOG.append({
            "tool": self.name,
            "action": "update_flight_status",
            "flight_id": flight_id,
            "status": status,
        })
        return True

    def apply_delay(self, flight_id: str, additional_delay_minutes: int) -> Flight | None:
        """Update estimated_departure by adding more delay minutes."""
        self._latency()
        from datetime import timedelta
        flight = store.FLIGHTS.get(flight_id)
        if not flight:
            return None
        new_estimated = flight.estimated_departure + timedelta(minutes=additional_delay_minutes)
        store.FLIGHTS[flight_id] = flight.model_copy(update={
            "estimated_departure": new_estimated,
            "status": FlightStatus.DELAYED,
        })
        return store.FLIGHTS[flight_id]
