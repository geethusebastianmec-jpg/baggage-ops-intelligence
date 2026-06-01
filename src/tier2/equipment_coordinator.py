"""Tier 2 — Equipment Failure Coordinator.

Triggered by BHS equipment failures (conveyor belt, CT scanner, sort chute).
A failure affects all bags in a zone, regardless of which flight they came from.

  START
    └──[find_impacted_bags]   BHS: which bags are in/queued for the failed zone?
           ├──[reroute_bags]  BHS: send bags via alternate BHS path   (parallel)
           └──[alert_maint]   Equipment: raise maintenance alert       (parallel)
                   └──[assess_impact]  Re-run triage for newly at-risk bags
                          └──[escalate_if_needed]  Notify AOCC if bags now missed
                                 └──END

All Tier 1. No LLM.
"""
from __future__ import annotations
from typing import Any, Annotated
import operator

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from src.models import BagStatus
from src.solver.triage import triage_bags
from src.tools.bhs import BHSTool
from src.tools.aodb import AODBTool
from src.tools.passenger_notify import PassengerNotifyTool
from src.tools import store

_bhs = BHSTool()
_aodb = AODBTool()
_notify = PassengerNotifyTool()

# Equipment failure types
FAILURE_TYPES = {"CONVEYOR", "SCANNER", "CHUTE", "SORTER"}


class EquipmentCoordinatorState(TypedDict, total=False):
    disruption_id: str
    equipment_id: str
    failed_zone: str
    failure_type: str
    # Set by find_impacted_bags
    impacted_bag_tags: list[str]
    # Set by parallel nodes
    bags_rerouted: int
    reroute_failed: list[str]
    maintenance_alerted: bool
    # Set by assess_impact
    newly_at_risk: list[str]
    # Actions
    actions_taken: Annotated[list[dict[str, Any]], operator.add]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def find_impacted_bags(state: EquipmentCoordinatorState) -> dict[str, Any]:
    """Tier 0 — identify all bags in or queued for the failed zone."""
    failed_zone = state.get("failed_zone", "")
    location_pattern = f"BHS_ZONE_{failed_zone}"

    impacted = [
        tag for tag, bag in store.BAGS.items()
        if location_pattern in bag.current_location
        and bag.status not in (BagStatus.LOADED, BagStatus.CONFIRMED_LOADED,
                               BagStatus.DELIVERED, BagStatus.MISSED)
    ]

    return {
        "impacted_bag_tags": impacted,
        "actions_taken": [{
            "node": "find_impacted_bags", "tool": "bhs",
            "result": f"Zone {failed_zone} failure: {len(impacted)} bags impacted.",
            "bag_tags": impacted,
        }],
    }


def reroute_bags(state: EquipmentCoordinatorState) -> dict[str, Any]:
    """Tier 1 — divert impacted bags to an alternate BHS path."""
    impacted = state.get("impacted_bag_tags", [])
    failed_zone = state.get("failed_zone", "")

    # Alternate zone: simple rule — if zone is B, try C, else try B
    alt_zone = "C" if failed_zone == "B" else "B"
    alt_gate = f"{alt_zone}0"   # simplified gate name for demo

    rerouted = []
    failed = []
    for tag in impacted:
        bag = store.BAGS.get(tag)
        if bag:
            success = _bhs.divert_to_gate([tag], alt_gate, f"BHS_ZONE_{alt_zone}")
            if success:
                rerouted.append(tag)
            else:
                failed.append(tag)

    return {
        "bags_rerouted": len(rerouted),
        "reroute_failed": failed,
        "actions_taken": [{
            "node": "reroute_bags", "tool": "bhs",
            "result": (
                f"Rerouted {len(rerouted)} bags to alternate zone {alt_zone}. "
                f"Failed: {len(failed)}."
            ),
            "rerouted": rerouted,
        }],
    }


def alert_maintenance(state: EquipmentCoordinatorState) -> dict[str, Any]:
    """Tier 1 — raise maintenance alert for failed equipment."""
    equipment_id = state.get("equipment_id", "UNKNOWN")
    failure_type = state.get("failure_type", "UNKNOWN")
    failed_zone = state.get("failed_zone", "")

    # In production: call maintenance ticketing system
    # In demo: log the alert
    store.ACTION_LOG.append({
        "tool": "maintenance",
        "action": "raise_alert",
        "equipment_id": equipment_id,
        "failure_type": failure_type,
        "zone": failed_zone,
        "priority": "HIGH" if failure_type in ("CONVEYOR", "SORTER") else "MEDIUM",
    })

    return {
        "maintenance_alerted": True,
        "actions_taken": [{
            "node": "alert_maintenance", "tool": "maintenance",
            "result": f"Maintenance alert raised: {failure_type} failure on {equipment_id} in zone {failed_zone}.",
        }],
    }


def assess_impact(state: EquipmentCoordinatorState) -> dict[str, Any]:
    """Tier 1 — check if any rerouted bags are now at risk due to the delay.

    Equipment failures add ~10-15 minutes to bag processing time.
    Re-run triage on rerouted bags with reduced departure windows.
    """
    rerouted_count = state.get("bags_rerouted", 0)
    failed_zone = state.get("failed_zone", "")
    EQUIPMENT_DELAY_MINUTES = 12  # typical delay added by zone failure

    newly_at_risk = []
    for tag, bag in store.BAGS.items():
        if bag.status == BagStatus.IN_TRANSIT and bag.destination_flight:
            window = _aodb.get_departure_window_minutes(bag.destination_flight)
            if window > 0:
                conn_data = [{"bag_tag": tag, "move_time_minutes": 8 + EQUIPMENT_DELAY_MINUTES}]
                result = triage_bags(conn_data, window, crew_available=True)
                if result.unrecoverable:
                    newly_at_risk.append(tag)
                    _notify.notify_bag_at_risk(bag.passenger_id, tag, bag.destination_flight)

    return {
        "newly_at_risk": newly_at_risk,
        "actions_taken": [{
            "node": "assess_impact", "tool": "triage+passenger_notify",
            "result": (
                f"Impact assessment: {newly_at_risk} bags now at risk due to "
                f"{EQUIPMENT_DELAY_MINUTES}-min equipment delay. Passengers notified."
                if newly_at_risk else
                "Impact assessment: no bags put at risk by equipment failure."
            ),
        }],
    }


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_equipment_coordinator() -> StateGraph:
    graph = StateGraph(EquipmentCoordinatorState)

    graph.add_node("find_impacted_bags", find_impacted_bags)
    graph.add_node("reroute_bags", reroute_bags)
    graph.add_node("alert_maintenance", alert_maintenance)
    graph.add_node("assess_impact", assess_impact)

    graph.add_edge(START, "find_impacted_bags")
    graph.add_edge("find_impacted_bags", "reroute_bags")
    graph.add_edge("find_impacted_bags", "alert_maintenance")
    graph.add_edge("reroute_bags", "assess_impact")
    graph.add_edge("alert_maintenance", "assess_impact")
    graph.add_edge("assess_impact", END)

    return graph


equipment_coordinator = build_equipment_coordinator().compile()
