"""Baggage Handling System mock tool.

Covers: bag location queries, transfer risk identification, exception routing.
"""
import time
from typing import Any

from src.models import Bag, BagStatus, ExceptionTicket, ExceptionType, TransferConnection
from src.tools import store
from src.tools.base import BaseTool


class BHSTool(BaseTool):
    name = "bhs"

    def query_bag(self, bag_tag: str) -> Bag | None:
        self._latency()
        return store.BAGS.get(bag_tag)

    def query_transfer_risks(self, inbound_flight: str) -> list[TransferConnection]:
        """Return all transfer connections where the inbound flight matches."""
        self._latency()
        at_risk = []
        for connections in store.CONNECTIONS.values():
            for conn in connections:
                if conn.inbound_flight == inbound_flight and conn.is_at_risk:
                    at_risk.append(conn)
        return at_risk

    def get_connections_for_flight(self, inbound_flight: str) -> list[TransferConnection]:
        """Return all connections (at-risk or not) for an inbound flight."""
        self._latency()
        result = []
        for connections in store.CONNECTIONS.values():
            for conn in connections:
                if conn.inbound_flight == inbound_flight:
                    result.append(conn)
        return result

    def update_bag_status(self, bag_tag: str, status: BagStatus, location: str = "") -> bool:
        self._latency()
        if self._should_fail():
            return False
        bag = store.BAGS.get(bag_tag)
        if not bag:
            return False
        store.BAGS[bag_tag] = bag.model_copy(update={"status": status, "current_location": location or bag.current_location})
        return True

    def open_exception_routing(
        self, bag_tags: list[str], reason: str, decision_id: str = "", disruption_id: str = ""
    ) -> ExceptionTicket:
        self._latency()
        if self._should_fail():
            raise RuntimeError("BHS exception routing service temporarily unavailable")

        ticket = ExceptionTicket(
            bag_tags=bag_tags,
            exception_type=ExceptionType.TRANSFER_AT_RISK,
            reason=reason,
        )
        for tag in bag_tags:
            self.update_bag_status(tag, BagStatus.EXCEPTION, "BHS_EXCEPTION_QUEUE")

        record = {
            "tool": self.name,
            "action": "open_exception_routing",
            "bag_tags": bag_tags,
            "ticket_id": ticket.ticket_id,
            "reason": reason,
        }
        store.ACTION_LOG.append(record)
        return ticket

    def mark_bag_missed(self, bag_tag: str) -> bool:
        self._latency()
        bag = store.BAGS.get(bag_tag)
        if not bag:
            return False
        store.BAGS[bag_tag] = bag.model_copy(update={"status": BagStatus.MISSED})
        store.ACTION_LOG.append({"tool": self.name, "action": "mark_bag_missed", "bag_tag": bag_tag})
        return True

    def confirm_bag_loaded(self, bag_tag: str, flight_id: str) -> bool:
        """Confirming scan — bag physically scanned onto the outbound aircraft.

        In production this is triggered by an actual BHS scan event arriving after
        the bag is loaded. In the demo it is called explicitly after route_bags
        to simulate a successful load confirmation.
        """
        self._latency()
        bag = store.BAGS.get(bag_tag)
        if not bag:
            return False
        store.BAGS[bag_tag] = bag.model_copy(
            update={"status": BagStatus.CONFIRMED_LOADED,
                    "current_location": f"HOLD_{flight_id}"}
        )
        store.ACTION_LOG.append({
            "tool": self.name,
            "action": "confirm_bag_loaded",
            "bag_tag": bag_tag,
            "flight_id": flight_id,
        })
        return True

    def place_security_hold(self, bag_tag: str, reason: str) -> bool:
        """Flag a bag as SECURITY_HOLD and pull it from the BHS queue.

        The bag cannot be loaded until security clears it.
        In production: sends a divert command to the BHS controller
        and opens a compliance ticket in the security management system.
        """
        self._latency()
        bag = store.BAGS.get(bag_tag)
        if not bag:
            return False
        from src.models import ExceptionType
        store.BAGS[bag_tag] = bag.model_copy(
            update={"status": BagStatus.EXCEPTION, "current_location": "SECURITY_HOLD"}
        )
        store.ACTION_LOG.append({
            "tool": self.name,
            "action": "place_security_hold",
            "bag_tag": bag_tag,
            "reason": reason,
            "exception_type": ExceptionType.SECURITY_HOLD,
        })
        return True

    def clear_security_hold(self, bag_tag: str) -> bool:
        """Mark a security hold as cleared — bag can now be rebooked."""
        self._latency()
        bag = store.BAGS.get(bag_tag)
        if not bag:
            return False
        store.BAGS[bag_tag] = bag.model_copy(
            update={"status": BagStatus.IN_TRANSIT, "current_location": "SECURITY_CLEARED"}
        )
        store.ACTION_LOG.append({"tool": self.name, "action": "clear_security_hold",
                                 "bag_tag": bag_tag})
        return True

    def divert_to_gate(self, bag_tags: list[str], new_gate: str, new_chute: str = "") -> bool:
        """Re-route bags to a different gate chute in the BHS (gate change scenario)."""
        self._latency()
        if self._should_fail():
            return False
        location = new_chute or f"CHUTE_{new_gate}"
        for tag in bag_tags:
            bag = store.BAGS.get(tag)
            if bag:
                store.BAGS[tag] = bag.model_copy(
                    update={"status": BagStatus.IN_TRANSIT, "current_location": location}
                )
        store.ACTION_LOG.append({
            "tool": self.name,
            "action": "divert_to_gate",
            "bag_tags": bag_tags,
            "new_gate": new_gate,
        })
        return True
