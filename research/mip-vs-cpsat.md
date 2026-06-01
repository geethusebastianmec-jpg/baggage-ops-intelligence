# MIP vs CP-SAT for Airline Baggage IROPS

## The Core Distinction

The right solver depends on which question you are actually answering.

| Question | Solver | Why |
|---|---|---|
| Which flight should this bag travel on? | **MIP** | Network flow over a time-expanded graph with capacity constraints |
| How much capacity to allocate per flight? | **MIP** | Linear constraints, flow balance equations |
| Which 8 of 20 bags should the ramp crew rush first? | **CP-SAT** | Resource assignment under capacity, logic constraints |
| How do I schedule sorters, belts, and carts? | **CP-SAT** | Scheduling with temporal and resource constraints |
| If flight X cancels, which recovery workflow runs? | **CP-SAT** | Conditional/logical constraints don't linearise well |
| End-to-end IROPS platform | **Hybrid** | MIP for network rerouting, CP-SAT for execution scheduling |

---

## When MIP Is The Right Choice

MIP (Mixed-Integer Programming) shines when the problem is fundamentally a
**network flow or transportation problem**:

- Thousands of disrupted bags needing rerouting across a flight network
- Each bag assigned to exactly one flight leg or sequence of legs
- Capacity limits per flight, per time window
- Objective: minimise total delay, cost, or mishandled bags

**Typical formulation:** Multi-commodity flow MIP on a time-expanded network.

```
Variables:
  x[b, f] ∈ {0,1}   — bag b travels on flight f
  y[b]    ∈ {0,1}   — bag b is successfully rerouted (not lost)

Constraints:
  Σ x[b, f] ≤ capacity[f]          for each flight f    (capacity)
  Σ x[b, f] = 1                    for each bag b        (assignment)
  x[b, f] = 0 if bag misses connection window           (timing)

Objective:
  maximise Σ y[b] × priority[b]                         (recovery value)
```

**Why MIP over CP-SAT here:**
- Flow balance equations are linear — LP relaxation gives a tight bound
- Dual variables from the LP relaxation tell you which capacity constraints
  are binding (sensitivity analysis — invaluable for operations teams)
- Commercial solvers (Gurobi, CPLEX, HiGHS) solve instances with thousands
  of bags and hundreds of flights in seconds to minutes
- Optimality guarantees — you know you have the best rerouting plan, not just
  a good one

---

## When CP-SAT Is The Right Choice

CP-SAT (Constraint Programming with SAT) shines when the problem has
**many combinatorial and logical constraints** that do not linearise cleanly:

- Priority classes: VIP bags, crew bags, medical cargo, interline bags
- Conditional logic: "if flight X holds, then reroute bags B and C; else rebook"
- Resource scheduling: which sorter belt, which cart, which loading crew
- Workforce assignment: which ramp crew handles which exception task, in what zone
- Business rules: "never reroute a bag through more than 2 connections"

**Why CP-SAT over MIP here:**
- Conditional constraints (`if-then`, `all-different`, automaton constraints)
  cannot be expressed as linear inequalities without introducing many binary
  variables and big-M constants — this degrades MIP solver performance badly
- CP-SAT handles logical constraints natively and propagates them efficiently
- For scheduling problems with many resources and time windows, CP-SAT's
  interval variables and no-overlap constraints are purpose-built
- Re-optimisation is fast: CP-SAT can warm-start from a previous solution,
  which is essential during IROPS where conditions change every few minutes

---

## What We Built and What It Implies

### Our CP-SAT usage — correctly placed

Our `solve_contended()` in `src/solver/optimizer.py` answers:

> "Given N bags that could physically make the connection, but the ramp crew
> can only rush K simultaneously — which K do we save?"

**This is a resource assignment problem.** Decision variables are binary per bag.
Constraints are crew capacity (hard) and physical slack (hard). Objective is
weighted bag value. This is squarely in CP-SAT territory — the right choice.

### What we are missing — the MIP layer

Our current system does not have a network-level rerouting layer. When a bag
misses its connection (MISSED status), the system:

1. Marks the bag as MISSED ✓
2. Notifies the passenger ✓
3. Books it on the "next available flight" via a stub schedule tool ✗ — this
   is a naive sequential lookup, not an optimisation

What should happen instead:

> Given 200 bags that missed connections across a hub bank disruption, available
> flights over the next 12 hours, variable capacity per flight, and passenger
> priorities — what is the optimal rerouting plan that minimises total delay
> across all 200 passengers?

**This is a multi-commodity flow MIP.** The current stub cannot answer it.
A proper implementation would run a time-expanded network MIP using HiGHS
(open-source, Python-native via `highspy`) or OR-Tools MIP wrapper.

### The correct hybrid architecture

```
DISRUPTION EVENT
      ↓
Tier 1 triage: which bags are at risk? (deterministic arithmetic)
      ↓
Tier 2a CP-SAT: which bags to rush NOW under crew contention?
  → ramp crew assignment, exception routing
      ↓
Tier 2b MIP: for bags that cannot make it — how to reroute?
  → time-expanded network, capacity per flight, priority weighting
  → outputs: bag → flight assignment for all missed bags
      ↓
Tier 3 coordinator: sequence and dispatch both plans
```

---

## Implementation Roadmap

### Phase 1 — already done (CP-SAT)

`src/solver/optimizer.py` — resource assignment for bags that can still make
the connection. Crew contention → binary CP-SAT → which subset to rush.

**Status:** ✅ implemented and tested

### Phase 2 — the missing MIP layer

New file: `src/solver/rerouter.py`

```python
# Proposed interface
def reroute_missed_bags(
    missed_bags: list[BagForRerouting],     # bags that cannot make original connection
    available_flights: list[FlightLeg],     # candidate legs in next 12 hours
    capacity: dict[str, int],               # remaining capacity per flight_id
    priority_weights: dict[str, float],     # bag_tag → priority (VIP=2.0, normal=1.0)
    time_limit_seconds: float = 5.0,
) -> dict[str, str]:                        # bag_tag → new_flight_id
```

**Solver choice:** HiGHS via `highspy` (open source, no licence cost, solves
instances with 10,000+ variables in seconds).

**Formulation:** Multi-commodity flow on a time-expanded graph.

### Phase 3 — hybrid coordinator

Update `src/tier2/cancellation_coordinator.py` and `src/tier2/loading_failure_coordinator.py`
to call the MIP rerouter instead of the naive sequential lookup in `ScheduleTool`.

---

## Summary: Our Solver Placement Is Correct, Our Coverage Is Partial

| Question | Our solver | Correct? |
|---|---|---|
| Which bags to rush under crew limit? | CP-SAT | ✅ Correct — resource assignment |
| Hold or depart? | Arithmetic (`bags × $150 vs hold × $500`) | ✅ Correct — simple rule |
| Which missed bags to put on which flight? | Stub (naive sequential) | ❌ Should be MIP |
| Bag network rerouting at scale? | Not implemented | ❌ Missing — needs MIP |

The CP-SAT solver we have is in the right place for what it does. The gap is that
we have no network-level rerouting optimiser. When a bag is marked MISSED, it gets
put on "the next available flight" without any awareness of:
- How many other bags are also competing for that flight's capacity
- Whether a slightly later flight has more capacity and equal arrival time
- Which bags are highest priority among all missed bags across the hub bank

That gap is where a time-expanded network MIP would add the most value.

---

## References

- OR-Tools MIP documentation: https://developers.google.com/optimization/mip
- HiGHS open-source MIP solver: https://highs.dev
- Time-expanded network formulation for airline rerouting: academic literature
  on "integrated airline recovery" (flight + crew + passenger joint models)
- Large-Scale Airline Crew Recovery Using Mixed-Integer Optimization —
  Transportation Science 2025 (arXiv 2510.26831)
