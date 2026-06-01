"""Tier 2b — MIP rerouter for missed bags.

When bags cannot make their original connection (MISSED status), this solver
determines the optimal assignment of bags to available rerouting flights.

Formulation: Multi-commodity flow on a simplified time-expanded network.

  Decision variables:
    x[b, f] ∈ {0,1}  —  bag b is assigned to flight f

  Hard constraints:
    1. Capacity:     Σ_b x[b,f] ≤ remaining_capacity[f]   per flight
    2. Assignment:   Σ_f x[b,f] ≤ 1                        per bag (at most one flight)
    3. Feasibility:  x[b,f] = 0  if bag cannot make f
                     (flight departs before bag is ready, or wrong destination)

  Objective (maximise):
    Σ_{b,f} x[b,f] × (priority[b] - delay_penalty[f])

  delay_penalty = departs_in_hours × 0.05  (prefer earlier flights, gently)

Solver: OR-Tools CBC (already installed via ortools package, no extra licence).

At realistic scale (200 bags, 20 candidate flights) CBC solves in well under
5 seconds. The 5-second time limit returns the best feasible solution found.

Compare to CP-SAT (src/solver/optimizer.py):
  CP-SAT answers: "which bags to rush NOW under crew contention"
    → resource assignment, fast re-optimisation, logic constraints
  MIP  answers: "which flight should each missed bag travel on"
    → network flow, capacity allocation, optimality guarantees, sensitivity
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:
    from ortools.linear_solver import pywraplp
    _MIP_AVAILABLE = True
except ImportError:
    _MIP_AVAILABLE = False


@dataclass
class BagForRerouting:
    bag_tag: str
    passenger_id: str
    destination: str            # IATA destination airport code
    priority: float = 1.0       # 1.0=normal, 1.5=tight-connection, 2.0=VIP/medical
    earliest_ready_minutes: int = 30  # minutes before bag can be processed for rerouting


@dataclass
class FlightLeg:
    flight_id: str
    origin: str
    destination: str
    departs_in_minutes: int     # minutes from now
    remaining_capacity: int     # bags still loadable


@dataclass
class RerouteResult:
    assignments: dict[str, str | None]   # bag_tag → flight_id  (None = no flight found)
    solver_status: str                   # OPTIMAL / FEASIBLE / INFEASIBLE / TIMEOUT
    bags_rerouted: int
    bags_stranded: int                   # no viable flight found
    reasoning: str


def reroute_missed_bags(
    bags: list[BagForRerouting],
    flights: list[FlightLeg],
    time_limit_seconds: float = 5.0,
) -> RerouteResult:
    """
    MIP optimal rerouting of missed bags onto available flights.

    Returns the assignment that maximises total weighted recovery subject to
    capacity, timing, and single-assignment constraints.

    Falls back to greedy (earliest viable flight, priority-ordered) if the
    MIP solver is unavailable.
    """
    if not bags:
        return RerouteResult({}, 'OPTIMAL', 0, 0, 'No bags to reroute.')

    # Filter to candidate (bag, flight) pairs that are physically feasible
    # —  correct destination AND flight departs after bag is ready
    candidates: list[tuple[int, int]] = []
    for i, bag in enumerate(bags):
        for j, flt in enumerate(flights):
            if (flt.destination == bag.destination
                    and flt.departs_in_minutes >= bag.earliest_ready_minutes
                    and flt.remaining_capacity > 0):
                candidates.append((i, j))

    if not candidates:
        return RerouteResult(
            {b.bag_tag: None for b in bags},
            'INFEASIBLE',
            0, len(bags),
            'No viable flight found for any bag (destination or timing mismatch).',
        )

    if _MIP_AVAILABLE:
        return _solve_mip(bags, flights, candidates, time_limit_seconds)
    return _greedy_fallback(bags, flights, candidates)


# ── MIP solve ──────────────────────────────────────────────────────────────────

def _solve_mip(
    bags: list[BagForRerouting],
    flights: list[FlightLeg],
    candidates: list[tuple[int, int]],
    time_limit_seconds: float,
) -> RerouteResult:
    solver = pywraplp.Solver.CreateSolver('CBC')
    solver.SetTimeLimit(int(time_limit_seconds * 1000))

    # Binary variables — one per feasible (bag, flight) pair
    x: dict[tuple[int, int], pywraplp.Variable] = {}
    for i, j in candidates:
        x[(i, j)] = solver.BoolVar(f'x_{i}_{j}')

    # Constraint 1: Capacity — at most remaining_capacity bags per flight
    for j, flt in enumerate(flights):
        flight_vars = [x[(i, j)] for (bi, bj) in candidates if bj == j for i in [bi]]
        if flight_vars:
            solver.Add(sum(flight_vars) <= flt.remaining_capacity)

    # Constraint 2: Single assignment — each bag goes on at most one flight
    for i in range(len(bags)):
        bag_vars = [x[(i, j)] for (bi, bj) in candidates if bi == i for j in [bj]]
        if bag_vars:
            solver.Add(sum(bag_vars) <= 1)

    # Objective: maximise weighted recovery
    # Priority weight minus a small delay penalty (prefer earlier flights)
    objective = solver.Objective()
    for i, j in candidates:
        bag = bags[i]
        flt = flights[j]
        delay_penalty = (flt.departs_in_minutes / 60.0) * 0.05
        weight = max(0.01, bag.priority - delay_penalty)
        objective.SetCoefficient(x[(i, j)], weight)
    objective.SetMaximization()

    status = solver.Solve()

    status_map = {
        pywraplp.Solver.OPTIMAL:   'OPTIMAL',
        pywraplp.Solver.FEASIBLE:  'FEASIBLE',
        pywraplp.Solver.INFEASIBLE:'INFEASIBLE',
        pywraplp.Solver.ABNORMAL:  'TIMEOUT',
        pywraplp.Solver.NOT_SOLVED:'NOT_SOLVED',
    }
    status_str = status_map.get(status, 'UNKNOWN')

    assignments: dict[str, str | None] = {b.bag_tag: None for b in bags}
    if status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        for i, j in candidates:
            if x[(i, j)].solution_value() > 0.5:
                assignments[bags[i].bag_tag] = flights[j].flight_id
                # Update remaining capacity in the in-memory flight record
                flights[j] = FlightLeg(
                    flight_id=flights[j].flight_id,
                    origin=flights[j].origin,
                    destination=flights[j].destination,
                    departs_in_minutes=flights[j].departs_in_minutes,
                    remaining_capacity=flights[j].remaining_capacity - 1,
                )

    rerouted = sum(1 for v in assignments.values() if v is not None)
    stranded = len(bags) - rerouted
    reasoning = (
        f"MIP ({status_str}): {rerouted}/{len(bags)} bags rerouted. "
        f"Solver wall time: {solver.WallTime()}ms."
    )
    return RerouteResult(assignments, status_str, rerouted, stranded, reasoning)


# ── Greedy fallback ────────────────────────────────────────────────────────────

def _greedy_fallback(
    bags: list[BagForRerouting],
    flights: list[FlightLeg],
    candidates: list[tuple[int, int]],
) -> RerouteResult:
    """Priority-ordered greedy: highest-priority bags first, earliest flight."""
    remaining_capacity = {j: flt.remaining_capacity for j, flt in enumerate(flights)}
    priority_order = sorted(range(len(bags)), key=lambda i: -bags[i].priority)

    assignments: dict[str, str | None] = {b.bag_tag: None for b in bags}
    for i in priority_order:
        # Find earliest viable flight with remaining capacity
        viable = []
        for bi, bj in candidates:
            if bi == i and remaining_capacity[bj] > 0:
                viable.append((bj, flights[bj].departs_in_minutes))
        viable.sort(key=lambda t: t[1])
        if viable:
            j, _ = viable[0]
            assignments[bags[i].bag_tag] = flights[j].flight_id
            remaining_capacity[j] -= 1

    rerouted = sum(1 for v in assignments.values() if v is not None)
    return RerouteResult(
        assignments, 'FEASIBLE (greedy)',
        rerouted, len(bags) - rerouted,
        f'Greedy fallback: {rerouted}/{len(bags)} bags assigned.',
    )
