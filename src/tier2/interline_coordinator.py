"""Tier 2 — Interline Coordinator.

Handles bags transferring between two different airlines (e.g. AA inbound → LH outbound).
These bags cannot be managed through the same BHS commands as on-line transfers because:
  1. The receiving airline controls the outbound aircraft and its hold manifest.
  2. The originating airline's BHS system cannot issue loading commands to the partner.
  3. Priority rules differ: IATA standard requires notification within specific time windows.

Workflow:
  START
    └──[identify_interline_bags]   Find all interline connections on the inbound flight
           └──[assess_risk]        Triage — same slack math, but flag even positive-slack bags
                  ├──[notify_partner]   Send IATA Type B message to partner airline's ops
                  └──[alert_transfer_desk]  Notify the airport interline transfer desk
                         └──[notify_passengers]  Passengers informed — different message for interline
                                └──END

Why interline bags get flagged even with positive slack:
  - The originating airline cannot guarantee the partner will accept a rush transfer.
  - Partner may have closed check-in for their outbound already.
  - Automated exception routing (BHS commands) only works within the same airline's systems.

The coordinator raises an alert and sends IATA notification. Physical recovery still
depends on the partner airline's response — this is the fundamental interline limitation.
"""
from __future__ import annotations
from typing import Any, Annotated
import operator

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from src.solver.triage import triage_bags
from src.tools.bhs import BHSTool
from src.tools.passenger_notify import PassengerNotifyTool
from src.tools import store

_bhs = BHSTool()
_notify = PassengerNotifyTool()

# IATA requires notification to the partner airline within this window (minutes)
# Source: IATA Baggage Handling Manual section 9.4
IATA_PARTNER_NOTIFICATION_WINDOW_MINUTES = 30


class InterlineCoordinatorState(TypedDict, total=False):
    disruption_id: str
    inbound_flight: str
    delay_minutes: int
    # Set by identify_interline_bags
    interline_connections: list[dict[str, Any]]
    partner_airlines: list[str]
    # Set by assess_risk
    at_risk_tags: list[str]        # positive slack but flagged (no direct control)
    impossible_tags: list[str]     # negative slack — physically cannot make it
    # Set by parallel nodes
    notifications_sent: int
    partner_alerts_sent: int
    # Actions
    actions_taken: Annotated[list[dict[str, Any]], operator.add]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def identify_interline_bags(state: InterlineCoordinatorState) -> dict[str, Any]:
    """Find all interline transfer connections for the inbound flight."""
    inbound = state["inbound_flight"]
    interline = []
    partners: set[str] = set()

    for tag, conns in store.CONNECTIONS.items():
        for conn in conns:
            if conn.inbound_flight == inbound and conn.is_at_risk and conn.is_interline:
                interline.append(conn.model_dump())
                if conn.partner_airline:
                    partners.add(conn.partner_airline)

    return {
        "interline_connections": interline,
        "partner_airlines": sorted(partners),
        "actions_taken": [{
            "node": "identify_interline_bags", "tool": "bhs",
            "result": (
                f"Found {len(interline)} interline transfer bags on {inbound}. "
                f"Partner airlines: {sorted(partners) or 'none'}."
            ),
        }],
    }


def assess_risk(state: InterlineCoordinatorState) -> dict[str, Any]:
    """Triage interline bags — flag ALL at-risk bags for manual oversight.

    Unlike on-line transfers, positive slack does NOT guarantee recovery.
    Even a bag with 15-minute slack may miss if the partner airline won't
    accept an automated rush transfer. We flag both categories.
    """
    connections = state.get("interline_connections", [])
    delay = state.get("delay_minutes", 0)

    at_risk = []
    impossible = []

    for conn in connections:
        tag = conn["bag_tag"]
        window = conn.get("connection_window_minutes", 0)
        move_time = conn.get("move_time_minutes", 8)
        slack = window - move_time

        if slack >= 0:
            # Positive slack — physically possible but NOT guaranteed (no direct control)
            at_risk.append(tag)
        else:
            # Negative slack — physically impossible regardless
            impossible.append(tag)

    return {
        "at_risk_tags": at_risk,
        "impossible_tags": impossible,
        "actions_taken": [{
            "node": "assess_risk", "tool": "triage",
            "result": (
                f"Interline triage: {len(at_risk)} bags at risk (positive slack but no direct control), "
                f"{len(impossible)} physically impossible. All flagged for partner notification."
            ),
        }],
    }


def notify_partner(state: InterlineCoordinatorState) -> dict[str, Any]:
    """Send IATA-standard notification to partner airline operations.

    In production: sends IATA Type B message (MVT or BKD format) to the
    partner airline's OCC email/SITA address within the required window.
    In demo: logs the notification to the action log.
    """
    partners = state.get("partner_airlines", [])
    at_risk = state.get("at_risk_tags", [])
    impossible = state.get("impossible_tags", [])
    inbound = state["inbound_flight"]
    delay = state.get("delay_minutes", 0)

    notifications = 0
    for partner in partners:
        # In production: send IATA Type B message to partner SITA address
        store.ACTION_LOG.append({
            "tool": "iata_type_b",
            "action": "partner_notification",
            "partner_airline": partner,
            "inbound_flight": inbound,
            "delay_minutes": delay,
            "at_risk_bags": at_risk,
            "impossible_bags": impossible,
            "message_type": "TRANSFER_RISK_ALERT",
            "iata_window_met": True,  # Would check actual timing in production
        })
        notifications += 1

    return {
        "partner_alerts_sent": notifications,
        "actions_taken": [{
            "node": "notify_partner", "tool": "iata_type_b",
            "result": (
                f"IATA Type B alert sent to {notifications} partner airline(s): "
                f"{partners}. {len(at_risk)} at-risk, {len(impossible)} impossible bags flagged."
            ),
        }],
    }


def alert_transfer_desk(state: InterlineCoordinatorState) -> dict[str, Any]:
    """Alert the airport's interline transfer desk for physical intervention."""
    at_risk = state.get("at_risk_tags", [])
    impossible = state.get("impossible_tags", [])
    partners = state.get("partner_airlines", [])

    store.ACTION_LOG.append({
        "tool": "transfer_desk",
        "action": "interline_alert",
        "at_risk_bags": at_risk,
        "impossible_bags": impossible,
        "partner_airlines": partners,
        "requires_human_intervention": True,
    })

    return {
        "actions_taken": [{
            "node": "alert_transfer_desk", "tool": "transfer_desk",
            "result": (
                f"Transfer desk alerted: {len(at_risk)} bags need physical coordination "
                f"with partners {partners}. Human intervention required — "
                "automated BHS commands cannot cross airline boundaries."
            ),
        }],
    }


def notify_passengers(state: InterlineCoordinatorState) -> dict[str, Any]:
    """Notify passengers — interline message is different from on-line transfer.

    For interline bags: we cannot confirm recovery the way we can for on-line bags.
    The message is honest: bag is at risk, we are coordinating with the partner airline.
    """
    at_risk = state.get("at_risk_tags", [])
    impossible = state.get("impossible_tags", [])
    sent = 0

    for tag in at_risk:
        bag = store.BAGS.get(tag)
        if bag:
            _notify.notify_bag_at_risk(
                bag.passenger_id, tag,
                f"(interline via {bag.partner_airline or 'partner airline'})"
            )
            sent += 1

    for tag in impossible:
        bag = store.BAGS.get(tag)
        if bag:
            _notify.notify_bag_missed(bag.passenger_id, tag)
            sent += 1

    return {
        "notifications_sent": sent,
        "actions_taken": [{
            "node": "notify_passengers", "tool": "passenger_notify",
            "result": (
                f"Passengers notified: {len(at_risk)} AT_RISK (interline coordination underway), "
                f"{len(impossible)} MISSED. Total: {sent}."
            ),
        }],
    }


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_interline_coordinator() -> StateGraph:
    graph = StateGraph(InterlineCoordinatorState)

    graph.add_node("identify_interline_bags", identify_interline_bags)
    graph.add_node("assess_risk", assess_risk)
    graph.add_node("notify_partner", notify_partner)
    graph.add_node("alert_transfer_desk", alert_transfer_desk)
    graph.add_node("notify_passengers", notify_passengers)

    graph.add_edge(START, "identify_interline_bags")
    graph.add_edge("identify_interline_bags", "assess_risk")
    # Parallel: notify partner + alert transfer desk simultaneously
    graph.add_edge("assess_risk", "notify_partner")
    graph.add_edge("assess_risk", "alert_transfer_desk")
    # Converge at passenger notification
    graph.add_edge("notify_partner", "notify_passengers")
    graph.add_edge("alert_transfer_desk", "notify_passengers")
    graph.add_edge("notify_passengers", END)

    return graph


interline_coordinator = build_interline_coordinator().compile()
