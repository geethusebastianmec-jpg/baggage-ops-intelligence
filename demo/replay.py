"""Measurement replay harness.

Runs a batch of disruption scenarios through the system and compares outcomes
against a manual baseline. This is how you prove the system is useful:

  "On N replayed disruptions, the system saved X% more bags
   than the manual baseline, with Y ms median decision time."

Usage:
  python demo/replay.py

Manual baseline model:
  A human AOCC coordinator handling the same disruptions would:
  - Take 3-5 minutes to make each phone call
  - Handle only one inbound flight at a time
  - Save only the first 2-3 bags they have time to route
  - Miss all bags on cascading simultaneous delays
  We model this as: save min(3, recoverable_bags) per event, sequentially.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

MANUAL_BASELINE_MAX_BAGS_PER_CALL = 3      # human saves at most 3 bags per phone call
MANUAL_BASELINE_DECISION_TIME_MS = 180_000  # 3 minutes per phone call


@dataclass
class ScenarioResult:
    name: str
    event_type: str
    system_saved: int
    system_missed: int
    system_decision_ms: int
    baseline_saved: int
    baseline_missed: int
    total_at_risk: int
    error: str | None = None


@dataclass
class ReplayStats:
    results: list[ScenarioResult] = field(default_factory=list)

    @property
    def total_at_risk(self) -> int:
        return sum(r.total_at_risk for r in self.results)

    @property
    def system_total_saved(self) -> int:
        return sum(r.system_saved for r in self.results)

    @property
    def baseline_total_saved(self) -> int:
        return sum(r.baseline_saved for r in self.results)

    @property
    def improvement_pct(self) -> float:
        if self.baseline_total_saved == 0:
            return 0.0
        return (self.system_total_saved - self.baseline_total_saved) / self.total_at_risk * 100

    @property
    def median_decision_ms(self) -> int:
        if not self.results:
            return 0
        times = sorted(r.system_decision_ms for r in self.results if not r.error)
        return times[len(times) // 2] if times else 0

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.error)


# ── Scenarios ─────────────────────────────────────────────────────────────────

def _make_delay_scenario(
    name: str,
    inbound: str,
    delay_min: int,
    outbound: str,
    window_min: int,
    n_zone_b: int,
    n_zone_d: int,
) -> tuple[dict, int]:
    """Build a seed + event for a delay scenario. Returns (event_dict, expected_recoverable)."""
    from src.tools import store
    from src.models import (
        Bag, Flight, FlightStatus, LoadPlan, TransferConnection, CrewStatus,
    )
    now = datetime.now(timezone.utc)

    store.FLIGHTS[inbound] = Flight(
        flight_id=inbound, airline="AA", origin="ORD", destination="JFK",
        scheduled_departure=now - timedelta(minutes=delay_min),
        estimated_departure=now, gate="B4", terminal="B", status=FlightStatus.DELAYED,
    )
    store.FLIGHTS[outbound] = Flight(
        flight_id=outbound, airline="AA", origin="JFK", destination="LHR",
        scheduled_departure=now + timedelta(minutes=window_min),
        estimated_departure=now + timedelta(minutes=window_min),
        gate="B12", terminal="B",
    )
    store.LOAD_PLANS[outbound] = LoadPlan(
        flight_id=outbound, aircraft_type="B737",
        max_weight_kg=15000.0, current_weight_kg=10000.0, bag_count=60,
    )
    store.CREW_STATUS["B"] = CrewStatus(
        zone="B", available_crew=4, total_crew=6, active_tasks=1, can_take_exception=True,
    )

    for i in range(n_zone_b):
        tag = f"BA-{name}-B{i:02d}"
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=f"P{name}{i}", passenger_name=f"Pax {i}",
            origin_flight=inbound, destination_flight=outbound,
            final_destination="LHR", current_location="BHS_ZONE_B",
        )
        store.CONNECTIONS[tag] = [TransferConnection(
            bag_tag=tag, passenger_id=f"P{name}{i}",
            inbound_flight=inbound, outbound_flight=outbound,
            connection_window_minutes=window_min, minimum_connection_time=25,
            move_time_minutes=8, is_at_risk=True,
        )]

    for i in range(n_zone_d):
        tag = f"BA-{name}-D{i:02d}"
        store.BAGS[tag] = Bag(
            bag_tag=tag, passenger_id=f"PD{name}{i}", passenger_name=f"Deep Pax {i}",
            origin_flight=inbound, destination_flight=outbound,
            final_destination="LHR", current_location="BHS_ZONE_D",
        )
        store.CONNECTIONS[tag] = [TransferConnection(
            bag_tag=tag, passenger_id=f"PD{name}{i}",
            inbound_flight=inbound, outbound_flight=outbound,
            connection_window_minutes=window_min, minimum_connection_time=25,
            move_time_minutes=26, is_at_risk=True,
        )]

    expected_recoverable = n_zone_b if window_min >= 8 else 0
    return {
        "event_type": "FLIGHT_DELAY",
        "payload": {"flight_id": inbound, "delay_minutes": delay_min},
        "severity": "HIGH",
        "affected_flights": [inbound],
    }, expected_recoverable


def _run_scenario(name: str, event_dict: dict, expected_recoverable: int, total_bags: int) -> ScenarioResult:
    from src.models import DisruptionEvent, DisruptionType, Severity, BagStatus
    from src.tier1.supervisor import StrategicSupervisor
    from src.tools import store

    event = DisruptionEvent(
        event_type=DisruptionType(event_dict["event_type"]),
        payload=event_dict["payload"],
        severity=Severity(event_dict.get("severity", "MEDIUM")),
        affected_flights=event_dict.get("affected_flights", []),
    )

    t0 = time.time()
    try:
        result = StrategicSupervisor().process(event)
        elapsed_ms = int((time.time() - t0) * 1000)
        error = None if not result.get("errors") else str(result["errors"])
    except Exception as exc:
        return ScenarioResult(
            name=name, event_type=event_dict["event_type"],
            system_saved=0, system_missed=total_bags,
            system_decision_ms=int((time.time() - t0) * 1000),
            baseline_saved=min(MANUAL_BASELINE_MAX_BAGS_PER_CALL, expected_recoverable),
            baseline_missed=total_bags - min(MANUAL_BASELINE_MAX_BAGS_PER_CALL, expected_recoverable),
            total_at_risk=total_bags, error=str(exc),
        )

    saved = len([t for t, b in store.BAGS.items()
                 if b.status == BagStatus.CONFIRMED_LOADED and b.destination_flight])
    missed = len([t for t, b in store.BAGS.items() if b.status == BagStatus.MISSED])

    baseline_saved = min(MANUAL_BASELINE_MAX_BAGS_PER_CALL, expected_recoverable)
    baseline_missed = total_bags - baseline_saved

    return ScenarioResult(
        name=name, event_type=event_dict["event_type"],
        system_saved=saved, system_missed=missed,
        system_decision_ms=elapsed_ms,
        baseline_saved=baseline_saved, baseline_missed=baseline_missed,
        total_at_risk=total_bags, error=error,
    )


# ── Replay run ────────────────────────────────────────────────────────────────

SCENARIOS = [
    # (name, inbound, delay, outbound, window, n_zone_b, n_zone_d)
    ("hub-tight",      "SC401", 32, "SC501", 25, 5, 2),   # tight window — mixed
    ("hub-generous",   "SC402", 10, "SC502", 40, 6, 2),   # generous window — all save
    ("hub-critical",   "SC403", 45, "SC503", 5,  0, 4),   # window too short — all miss
    ("hub-moderate",   "SC404", 20, "SC504", 30, 4, 1),   # moderate delay — partial
    ("hub-large-bank", "SC405", 25, "SC505", 20, 8, 3),   # large bank at hub
]


def run() -> None:
    from src.tools import store
    from src.tools.passenger_notify import PassengerNotifyTool

    console.print()
    console.print("[bold cyan]Measurement Replay Harness[/bold cyan]")
    console.print("[dim]Compares system outcomes against simulated manual baseline[/dim]")
    console.print()

    stats = ReplayStats()

    for name, inbound, delay, outbound, window, n_b, n_d in SCENARIOS:
        store.reset()
        PassengerNotifyTool.clear()

        event_dict, expected_rec = _make_delay_scenario(
            name, inbound, delay, outbound, window, n_b, n_d
        )
        total = n_b + n_d

        console.print(f"  Running [yellow]{name}[/yellow] — "
                      f"{inbound} +{delay}min, window={window}min, "
                      f"{n_b} Zone-B + {n_d} Zone-D bags...", end=" ")

        result = _run_scenario(name, event_dict, expected_rec, total)
        stats.results.append(result)

        status = "[green]OK[/green]" if not result.error else "[red]ERROR[/red]"
        console.print(f"{status} ({result.system_decision_ms}ms)")

    # ── Results table ─────────────────────────────────────────────────────────
    console.print()
    table = Table(title="[bold]Replay Results[/bold]", box=box.ROUNDED)
    table.add_column("Scenario", style="bold")
    table.add_column("At risk", justify="right")
    table.add_column("System saved", justify="right", style="green")
    table.add_column("Baseline saved", justify="right", style="yellow")
    table.add_column("Diff", justify="right")
    table.add_column("Decision", justify="right")

    for r in stats.results:
        delta = r.system_saved - r.baseline_saved
        delta_str = f"[green]+{delta}[/green]" if delta > 0 else f"[red]{delta}[/red]" if delta < 0 else "0"
        table.add_row(
            r.name,
            str(r.total_at_risk),
            str(r.system_saved),
            str(r.baseline_saved),
            delta_str,
            f"{r.system_decision_ms}ms" + (" [red]ERR[/red]" if r.error else ""),
        )

    console.print(table)

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print()
    console.print(f"  Total bags at risk:    [bold]{stats.total_at_risk}[/bold]")
    console.print(f"  System saved:          [bold green]{stats.system_total_saved}[/bold green] "
                  f"({stats.system_total_saved/max(stats.total_at_risk,1)*100:.0f}%)")
    console.print(f"  Baseline saved:        [bold yellow]{stats.baseline_total_saved}[/bold yellow] "
                  f"({stats.baseline_total_saved/max(stats.total_at_risk,1)*100:.0f}%)")
    console.print(f"  Improvement:           [bold]+{stats.improvement_pct:.1f}% bags recovered[/bold]")
    console.print(f"  Median decision time:  [bold]{stats.median_decision_ms}ms[/bold] "
                  f"(vs ~{MANUAL_BASELINE_DECISION_TIME_MS//1000//60} min manual)")
    if stats.error_count:
        console.print(f"  [red]Errors: {stats.error_count}[/red]")
    console.print()


if __name__ == "__main__":
    run()
