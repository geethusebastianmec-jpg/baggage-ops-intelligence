# Architecture Revision — Correct Tier Placement

## What Was Wrong and Why

The original prototype committed one category error: it used an LLM (Tier 4) to
answer a question that is pure arithmetic (Tier 1).

The `evaluate_feasibility` node in the Baggage Coordinator called Gemini to decide
which bags are RECOVERABLE vs UNRECOVERABLE. That decision is:

```
slack = minutes_until_outbound_closes − move_time_minutes
if slack >= 0 and crew available → RECOVERABLE
if slack < 0                     → UNRECOVERABLE
```

There is no judgment involved. The LLM was not needed, not appropriate, and
introduced cost, latency, and non-determinism into a safety-relevant calculation
that an ops team will require to be auditable and predictable.

The same error almost appeared in the Dispatch Coordinator, which used an LLM to
decide whether to hold a departure. That is also a cost comparison:
`bags_saved × $150 vs hold_minutes × $500`.

---

## The Correct Tier Hierarchy

From the field document:

| Tier | Tool | Question | Cost / risk |
|---|---|---|---|
| 0 | Database / state machine | Where is bag X right now? | Trivial |
| 1 | Deterministic rules (plain code) | Is this bag at risk? Who gets notified? | Instant, auditable |
| 2 | CP-SAT constraint solver | Multiple bags competing for scarce crew — what is the optimal set of actions? | Heavier, but exact and fast at this scale |
| 3 | Agent (thin orchestration loop) | Which of the above does this situation need, in what order? | Routes work, never does the math itself |
| 4 | LLM | Genuinely fuzzy, language-shaped judgment | Slow, costly, non-deterministic. Last resort. |

The coordinator (Tier 3) orchestrates. CP-SAT (Tier 2) optimizes. Rules (Tier 1)
decide the knowable. The database (Tier 0) remembers. Nothing does a job that a
cheaper, more predictable tier could do correctly.

---

## Bag Move Time vs. Minimum Connection Time

These are frequently confused and the confusion caused the original error.

**Minimum Connection Time (MCT)** — the total time a passenger needs to connect at
an airport. Includes: aircraft taxi + deplaning + terminal transit + security/customs
(if applicable) + gate walk + boarding. MCT at JFK: 60–90 minutes domestic,
90–150 minutes international.

**Physical bag move time** — time from the arriving aircraft's hold to the departing
aircraft's hold via ramp, tug, and manual loading. This has nothing to do with
passengers or MCT. It depends on:
- BHS zone the bag is currently in (closer to gate = shorter)
- Tug availability and route between gates
- Manual loading time at the outbound aircraft

**Research findings on bag move time:**
- Conveyor transit (check-in to gate): 10–20 minutes
- Aircraft to baggage claim: ~15 minutes average
- **8 minutes is the lower bound** for a bag already in the BHS near the correct
  terminal. Bags deep in the queue or requiring a cross-terminal tug run need 15–25 min.

**Implication for triage:** `move_time_minutes` is **per-bag**, not a single constant.
A bag currently in BHS Zone B (adjacent to the departure gate) has `move_time = 8`.
A bag in Zone D (far side of terminal, or waiting for belt unload) has `move_time = 22`.
This per-bag value is what makes some bags unrecoverable on a deterministic basis —
no LLM needed.

---

## The CP-SAT Model (Tier 2)

CP-SAT is invoked only when there is **resource contention**: more bags need rushing
than the crew can handle simultaneously. This is the only case where the "best subset"
question cannot be answered by a simple rule.

### When contention exists

```
simultaneous_capacity = available_crew_members × bags_per_crew  # e.g. 4 crew × 3 bags = 12
contention = len(recoverable_bags) > simultaneous_capacity
```

If no contention: all recoverable bags get rushed. Simple rule, no solver.

If contention: CP-SAT finds the optimal subset.

### Decision variables

```python
rush[b] ∈ {0, 1}   # 1 = rush the bag (save it); 0 = late delivery
```

### Hard constraints

```python
# Crew capacity: can only rush so many bags at once
sum(rush[b] for b in all_bags) <= simultaneous_capacity

# Deadline: can only rush a bag if it has positive slack
for b in bags:
    if b.slack_minutes < 0:
        rush[b] == 0   # physically impossible — force to 0
```

### Objective — minimize total cost

```python
minimize:
    sum(miss_cost[b] × (1 - rush[b]))     # cost of each missed bag (~$150)
  + sum(priority_penalty[b] × (1 - rush[b]))  # VIP / tight-connection passengers
```

At v1 scale (tens of bags, a handful of crew, a dozen flights at a hub bank): CP-SAT
returns optimal in **under 100ms**. Research confirms <1 second for under 100 variables.

### What CP-SAT does NOT do at v1

- Hold optimization (`hold[f] ∈ {0,1}`) — modelled as a Dispatch Coordinator
  concern, handled by the cost function in Tier 1
- Tug routing (Vehicle Routing Problem with Time Windows) — fold travel time into
  `move_time[b]` for now; separate VRP solver is a v2 addition
- Multi-hub cascades — single disruption scope for v1

---

## Revised Decision Flow (Correct Tiers)

```
FlightDelayed event arrives
    ↓
Coordinator (Tier 3) gathers state:
  - at-risk connections (Tier 0 reads)
  - departure window for outbound (Tier 0 read)
  - move_time_minutes per bag (Tier 0, per-bag from BHS zone)
  - crew availability (Tier 0 read)
    ↓
Triage (Tier 1 — pure math):
  for each bag:
    slack = departure_window − move_time_minutes
    recoverable if slack >= 0, else unrecoverable
    ↓
Contention check (Tier 1 — simple count):
  recoverable_count > simultaneous_capacity?
  NO → route all recoverable bags (Tier 1 rules)
  YES → CP-SAT optimizer (Tier 2)
    ↓
Dispatch (Tier 1 — cost comparison):
  save_value = recoverable_count × miss_cost_per_bag   ($150)
  hold_cost  = hold_minutes × delay_cost_per_minute    ($500)
  if save_value > hold_cost → HOLD
  else → DEPART
    ↓
Actions (Tier 1 lookup table):
  RUSH  → ramp + exception routing + AT_RISK passenger notify
  LATE  → mark missed + MISSED passenger notify
  HOLD  → dispatch hold request
```

The LLM never appears in this flow. The coordinator (Tier 3) sequences the steps
and handles retries on failure. That is the correct job for an agent.

---

## Where the LLM Still Belongs (Tier 4)

The Tier 1 Strategic Supervisor's **ReAct path** is the correct home for the LLM.
It is invoked only when:
- No playbook matches (genuinely novel disruption type)
- Compound simultaneous disruptions requiring cross-domain reasoning that cannot
  be pre-written as a rule

In those cases the LLM's job is to **decide which coordinators to activate and in what
order** — a routing decision, not a math decision. It still does not compute feasibility.
That happens in Tier 1 once the coordinator runs.

---

## Changes Required in Codebase

### Remove

| File | What to remove |
|---|---|
| `src/tier2/baggage_coordinator.py` | `evaluate_feasibility` node (Gemini call) |
| `src/tier2/dispatch_coordinator.py` | Gemini fallback in `decide_hold` |
| `langchain-google-genai` import | From baggage and dispatch coordinators |

### Add

| File | What to add |
|---|---|
| `src/solver/triage.py` | `triage_bags()` — per-bag slack math (Tier 1) |
| `src/solver/optimizer.py` | `solve_contended()` — CP-SAT model (Tier 2) |
| `src/models/bag.py` | `move_time_minutes: int = 8` field on `TransferConnection` |
| `demo/seed_data.py` | Per-bag `move_time_minutes` (BHS zone realistic values) |
| `requirements.txt` | `ortools` |

### Update

| File | Change |
|---|---|
| `src/tier2/baggage_coordinator.py` | Replace eval node with `triage_bags` + `check_contention` + `solve_if_contended` nodes |
| `src/tier2/dispatch_coordinator.py` | Replace LLM fallback with cost comparison rule |
| Tests | Remove LLM mocks from baggage coordinator tests — tests become simpler and deterministic |

---

## Demo Scenario Impact

With deterministic move times per BHS zone, the Hub Crisis demo produces the same
outcome (5 saved, 2 missed from AA401) for a physically correct reason:

| Bag | BHS Zone | move_time_minutes | slack (window=25 min) | Outcome |
|---|---|---|---|---|
| BA-001 to BA-005 | Zone B (near gate) | 8 min | 25 − 8 = **+17 min** | RUSH ✅ |
| BA-006, BA-007 | Zone D (far queue) | 22 min | 25 − 22 = **+3 min** | UNRECOVERABLE ❌ |

The "why" changes from "the LLM judged BA-006/007 too far" to "BA-006/007 are
physically 22 minutes from the gate and the window is only 25 minutes." The second is
auditable, repeatable, and true.

---

## Build Order for Revision

1. Add `move_time_minutes` to `TransferConnection` model
2. Write `src/solver/triage.py` — Tier 1 math (no dependencies)
3. Write `src/solver/optimizer.py` — Tier 2 CP-SAT (depends on `ortools`)
4. Update `src/tier2/baggage_coordinator.py` — swap nodes
5. Update `src/tier2/dispatch_coordinator.py` — swap hold logic
6. Update seed data with per-bag move times
7. Update tests — remove LLM mocks, add deterministic assertions
8. Update README and scenario coverage table

---

## Sources

- [OR-Tools CP-SAT Documentation](https://developers.google.com/optimization/cp/cp_solver)
- [CP-SAT Python API](https://or-tools.github.io/docs/pdoc/ortools/sat/python/cp_model.html)
- [Optimization of Transfer Baggage Handling — ResearchGate](https://www.researchgate.net/publication/350337915_Optimization_of_Transfer_Baggage_Handling_in_a_Major_Transit_Airport)
- [Minimum Connection Times — OAG](https://www.oag.com/blog/minimum-connection-times-insiders-guide)
- [Baggage Handling Times — Aviatopia](https://aviatopia.com/guides/baggage-handling)
- [Tier-Based Agent Architecture — Microsoft Azure AI](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/three-tiers-of-agentic-ai---and-when-to-use-none-of-them/4510377)
