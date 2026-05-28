"""Hub Crisis demo scenario runner.

Runs the full end-to-end demo without a live Kafka broker:
events are injected directly into the supervisor rather than via Kafka,
so the scenario works whether Docker is running or not.

Usage:
  python demo/scenario_runner.py
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.live import Live
from rich.columns import Columns

console = Console()


def _print_header():
    console.print()
    console.print(Panel(
        "[bold cyan]BAGGAGE OPS INTELLIGENCE — HUB CRISIS DEMO[/bold cyan]\n"
        "[dim]JFK Hub · 3 simultaneous delays · 12 bags at risk[/dim]",
        border_style="cyan",
    ))
    console.print()


def _print_flights():
    table = Table(title="[bold]Flight Status[/bold]", box=box.ROUNDED, border_style="blue")
    table.add_column("Flight", style="bold")
    table.add_column("Route")
    table.add_column("Status")
    table.add_column("Delay")
    table.add_column("At-Risk Bags")

    table.add_row("AA401", "ORD → JFK", "[red]DELAYED[/red]", "+32 min", "7 → AA501 (LHR)")
    table.add_row("AA402", "LAX → JFK", "[red]DELAYED[/red]", "+18 min", "3 → AA501 (LHR)")
    table.add_row("AA403", "MIA → JFK", "[yellow]DELAYED[/yellow]", "+11 min", "2 → AA502 (CDG) [green]✓ safe[/green]")
    table.add_row("AA501", "JFK → LHR", "[green]ON TIME[/green]", "—", "departs in 25 min")
    table.add_row("AA502", "JFK → CDG", "[green]ON TIME[/green]", "—", "departs in 40 min")
    console.print(table)
    console.print()


def _print_event(title: str, detail: str, color: str = "yellow"):
    console.print(f"[{color}]▶ {title}[/{color}]  [dim]{detail}[/dim]")


def _print_result(result: dict, flight_id: str):
    mode = result.get("mode", "?")
    playbook = result.get("playbook", result.get("react_reasoning", "REACT"))
    actions = result.get("all_actions", [])
    errors = result.get("errors", {})

    console.print(f"  [cyan]Mode:[/cyan] {mode}  [cyan]Playbook:[/cyan] {playbook}")
    console.print(f"  [cyan]Coordinators:[/cyan] {', '.join(result.get('coordinators_activated', []))}")
    console.print(f"  [cyan]Actions taken:[/cyan] {len(actions)}")
    if errors:
        for name, err in errors.items():
            console.print(f"  [red]Error in {name}:[/red] {err}")

    for action in actions:
        node = action.get("node", action.get("coordinator", "?"))
        result_text = action.get("result", "")[:80]
        console.print(f"    [dim]• [{node}][/dim] {result_text}")


def _print_final_summary():
    from src.tools import store
    from src.models import BagStatus
    from src.tools.passenger_notify import PassengerNotifyTool

    saved = [tag for tag, bag in store.BAGS.items()
             if bag.status == BagStatus.EXCEPTION and bag.destination_flight]
    missed = [tag for tag, bag in store.BAGS.items() if bag.status == BagStatus.MISSED]
    notified = PassengerNotifyTool.get_sent()
    actions = store.ACTION_LOG

    table = Table(title="\n[bold green]DEMO OUTCOME[/bold green]", box=box.DOUBLE_EDGE, border_style="green")
    table.add_column("Metric", style="bold")
    table.add_column("Result", justify="right")

    table.add_row("Bags routed (exception)", f"[green]{len(saved)}[/green]")
    table.add_row("Bags missed", f"[red]{len(missed)}[/red]")
    table.add_row("Passenger notifications sent", str(len(notified)))
    table.add_row("Total tool actions logged", str(len(actions)))
    console.print(table)

    if missed:
        console.print(f"\n[red]Missed bags:[/red] {', '.join(missed)}")
    if saved:
        console.print(f"[green]Routed bags:[/green] {', '.join(saved[:5])}{'...' if len(saved) > 5 else ''}")
    console.print()


def run():
    # Imports here so mock patches in tests work correctly
    from demo.seed_data import load
    from src.models import DisruptionEvent, DisruptionType, Severity
    from src.tier1.supervisor import StrategicSupervisor

    _print_header()
    _print_flights()

    console.print("[bold]Loading seed data...[/bold]")
    load()
    console.print("[green]✓ Seed data loaded[/green] — 5 flights, 40 bags, 12 at-risk connections\n")

    sup = StrategicSupervisor()
    start_time = time.time()

    # ── Event 1: AA401 delayed 32 min ─────────────────────────────────────────
    console.rule("[bold red]IROPS EVENT 1[/bold red]")
    _print_event("AA401 DELAYED +32 MIN", "ORD→JFK · 7 bags connecting to AA501 (LHR)", "red")
    t0 = time.time()
    e1 = DisruptionEvent(
        event_type=DisruptionType.FLIGHT_DELAY,
        payload={"flight_id": "AA401", "delay_minutes": 32},
        severity=Severity.HIGH,
        affected_flights=["AA401"],
    )
    r1 = sup.process(e1)
    console.print(f"  [dim]Processed in {time.time()-t0:.1f}s[/dim]")
    _print_result(r1, "AA401")
    console.print()

    # ── Event 2: AA402 delayed 18 min (500ms after E1) ────────────────────────
    time.sleep(0.5)
    console.rule("[bold yellow]IROPS EVENT 2[/bold yellow]")
    _print_event("AA402 DELAYED +18 MIN", "LAX→JFK · 3 bags connecting to AA501 (LHR)", "yellow")
    t0 = time.time()
    e2 = DisruptionEvent(
        event_type=DisruptionType.FLIGHT_DELAY,
        payload={"flight_id": "AA402", "delay_minutes": 18},
        severity=Severity.HIGH,
        affected_flights=["AA402"],
    )
    r2 = sup.process(e2)
    console.print(f"  [dim]Processed in {time.time()-t0:.1f}s[/dim]")
    _print_result(r2, "AA402")
    console.print()

    # ── Event 3: AA403 delayed 11 min (1s after E1) ───────────────────────────
    time.sleep(0.5)
    console.rule("[bold dim]IROPS EVENT 3[/bold dim]")
    _print_event("AA403 DELAYED +11 MIN", "MIA→JFK · 2 bags → AA502 (CDG) — window safe", "dim")
    t0 = time.time()
    e3 = DisruptionEvent(
        event_type=DisruptionType.FLIGHT_DELAY,
        payload={"flight_id": "AA403", "delay_minutes": 11},
        severity=Severity.MEDIUM,
        affected_flights=["AA403"],
    )
    r3 = sup.process(e3)
    console.print(f"  [dim]Processed in {time.time()-t0:.1f}s[/dim]")
    _print_result(r3, "AA403")
    console.print()

    elapsed = time.time() - start_time
    console.print(f"[bold]Total wall-clock time:[/bold] {elapsed:.1f}s")
    console.rule()
    _print_final_summary()


if __name__ == "__main__":
    run()
