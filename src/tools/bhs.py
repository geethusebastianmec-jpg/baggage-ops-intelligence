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
