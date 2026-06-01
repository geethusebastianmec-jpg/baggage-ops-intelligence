"""Tier 2 — CP-SAT optimizer for contended bag recovery.

Only called when has_contention() is True — i.e. more bags need rushing
than the crew can handle simultaneously. In that case simple rules cannot
decide which bags to save; we need the optimal subset.

The CP-SAT model:
    Variables:  rush[b] ∈ {0,1}  per recoverable bag (1 = save it)
    Constraint: sum(rush) <= crew_capacity
    Objective:  maximise  sum( rush[b] * cost_weight[b] )
                where cost_weight reflects miss_cost + priority bonus

Runtime: <100 ms at demo scale (≤100 bags). Falls back to greedy if
OR-Tools is not installed (so the system still works without the package).
"""
from __future__ import annotations
from dataclasses import dataclass, field

MISS_COST = 150       # $ per missed bag (industry figure)
PRIORITY_BONUS = 50   # extra weight for VIP / tight-connection passengers


@dataclass
class BagForOptimization:
    bag_tag: str
    slack_minutes: int        # must be >= 0 (unrecoverable bags excluded upstream)
    priority_weight: float = 1.0  # 1.0 = normal, 2.0 = VIP/tight-connection


def solve_contended(
    bags: list[BagForOptimization],
    crew_capacity: int,
) -> list[str]:
    """
    Returns the optimal subset of bag_tags to rush under crew contention.

    Args:
        bags:          recoverable bags only (slack >= 0 already verified by triage)
        crew_capacity: max bags that can be moved simultaneously

    Returns:
        list of bag_tags the solver decided to save
    """
    if not bags:
        return []

    candidates = [b for b in bags if b.slack_minutes >= 0]

    # No real contention among feasible bags
    if len(candidates) <= crew_capacity:
        return [b.bag_tag for b in candidates]

    try:
        return _solve_with_cpsat(candidates, crew_capacity)
    except Exception:
        return _greedy_fallback(candidates, crew_capacity)


def _solve_with_cpsat(
    candidates: list[BagForOptimization],
    crew_capacity: int,
) -> list[str]:
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()

    # Binary var per bag: 1 = rush (save), 0 = late-delivery (miss)
    rush = {b.bag_tag: model.new_bool_var(f"rush_{b.bag_tag}") for b in candidates}

    # Hard constraint: total simultaneous rushes <= crew capacity
    model.add(sum(rush.values()) <= crew_capacity)

    # Objective: maximise value of saved bags
    # Scale floats to integers — CP-SAT requires integer coefficients
    model.maximize(
        sum(
            rush[b.bag_tag] * int((MISS_COST + PRIORITY_BONUS * b.priority_weight) * 100)
            for b in candidates
        )
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0   # hard deadline
    status = solver.solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [b.bag_tag for b in candidates if solver.value(rush[b.bag_tag]) == 1]

    return _greedy_fallback(candidates, crew_capacity)


def _greedy_fallback(
    candidates: list[BagForOptimization],
    crew_capacity: int,
) -> list[str]:
    """Greedy: highest priority first, break ties by most slack."""
    ranked = sorted(
        candidates,
        key=lambda b: (b.priority_weight, b.slack_minutes),
        reverse=True,
    )
    return [b.bag_tag for b in ranked[:crew_capacity]]
