"""Tier 2 — Comms Domain Coordinator.

Fires passenger notifications for any bag status change event.
Read-only: never modifies bag or flight state.

  START → send_notifications → END
"""
from __future__ import annotations
from typing import Any

from langgraph.graph import StateGraph, START, END

from src.tier2.state import CommsCoordinatorState
from src.tools.passenger_notify import PassengerNotifyTool

_notify = PassengerNotifyTool()


def send_notifications(state: CommsCoordinatorState) -> dict[str, Any]:
    notifications = state.get("notifications", [])
    sent, failed = 0, 0

    for notif in notifications:
        passenger_id = notif["passenger_id"]
        bag_tag = notif["bag_tag"]
        notif_type = notif.get("type", "AT_RISK")

        if notif_type == "MISSED":
            ok = _notify.notify_bag_missed(passenger_id, bag_tag,
                                           notif.get("delivery_eta", "next available flight"))
        elif notif_type == "RECOVERED":
            ok = _notify.notify_bag_recovered(passenger_id, bag_tag)
        else:
            ok = _notify.notify_bag_at_risk(passenger_id, bag_tag,
                                            notif.get("outbound_flight", ""))
        if ok:
            sent += 1
        else:
            failed += 1

    return {
        "sent_count": sent,
        "failed_count": failed,
        "actions_taken": [{
            "node": "send_notifications",
            "tool": "passenger_notify",
            "result": f"Sent {sent}, failed {failed} out of {len(notifications)} notifications",
        }],
    }


def build_comms_coordinator() -> StateGraph:
    graph = StateGraph(CommsCoordinatorState)
    graph.add_node("send_notifications", send_notifications)
    graph.add_edge(START, "send_notifications")
    graph.add_edge("send_notifications", END)
    return graph


comms_coordinator = build_comms_coordinator().compile()
