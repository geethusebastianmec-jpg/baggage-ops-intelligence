"""Ground Service Provider (GSP) mock tool.

At most major airports, ramp operations are outsourced to a GSP
(Swissport, Menzies, dnata, etc.). The airline cannot issue direct BHS
commands to GSP-operated zones — it must go through the GSP's own
dispatch system via a separate API or ACARS message.

Key differences from airline-direct ramp control:
  - Response time: GSP acknowledgement takes 2-10 minutes (not seconds)
  - No guaranteed SLA for exception tasks unless contracted upfront
  - Priority: GSP serves multiple airlines; exception request may be queued
  - Data: GSP may not expose real-time crew availability to the airline

In production: calls the GSP's REST API or sends an ACARS message.
In demo: simulates GSP dispatch with configurable response delay and
acceptance probability.
"""
from __future__ import annotations

from src.models import GroundHandler, TaskTicket
from src.tools import store
from src.tools.base import BaseTool


class GSPTool(BaseTool):
    name = "gsp"

    # Simulated acceptance rates by GSP — some are more responsive than others
    _ACCEPTANCE_RATES: dict[str, float] = {
        GroundHandler.SWISSPORT: 0.85,  # good SLA coverage
        GroundHandler.MENZIES:   0.75,
        GroundHandler.DNATA:     0.90,
        GroundHandler.OTHER:     0.60,
        GroundHandler.AIRLINE:   1.00,  # always — use RampTool instead for airline zones
    }

    def request_exception_task(
        self,
        bag_tags: list[str],
        from_flight: str,
        to_flight: str,
        zone: str,
        handler: str,
    ) -> TaskTicket | None:
        """Submit an exception bag transfer request to the GSP's dispatch system.

        Returns a TaskTicket if the GSP accepts (creates a work order in their system).
        Returns None if the GSP is at capacity or doesn't accept exception requests.

        Response time is slower than airline-direct (GSP must acknowledge).
        """
        self._latency()

        # Simulated acceptance check
        import random
        acceptance_rate = self._ACCEPTANCE_RATES.get(handler, 0.70)
        if random.random() > acceptance_rate:
            store.ACTION_LOG.append({
                "tool": self.name,
                "action": "gsp_request_declined",
                "handler": handler,
                "zone": zone,
                "reason": f"{handler} GSP at capacity or no exception SLA for this flight pair",
            })
            return None

        ticket = TaskTicket(
            task_type=f"GSP_EXCEPTION_{handler}",
            bag_tags=bag_tags,
            from_flight=from_flight,
            to_flight=to_flight,
            assigned_zone=zone,
            eta_minutes=12,  # GSP exception tasks take longer than airline-direct
        )
        store.ACTION_LOG.append({
            "tool": self.name,
            "action": "gsp_task_submitted",
            "handler": handler,
            "zone": zone,
            "ticket_id": ticket.ticket_id,
            "bag_tags": bag_tags,
            "eta_minutes": ticket.eta_minutes,
        })
        return ticket

    def get_gsp_capacity(self, zone: str) -> dict[str, int] | None:
        """Query GSP for available capacity in a zone.

        In production: REST call to GSP's capacity API (if they expose one).
        In demo: reads from store (same as airline crew) but notes it's a GSP query.
        """
        self._latency()
        crew = store.CREW_STATUS.get(zone)
        if not crew:
            return None
        return {
            "zone": zone,
            "available": crew.available_crew,
            "handler": crew.handler,
        }
