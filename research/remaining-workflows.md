# Workflows — Status

## What a Workflow Is

A workflow is a predefined sequence of steps for a specific disruption type.
The coordinator's job is: receive event → select workflow → execute workflow.
The workflow contains the logic; the coordinator is just the runner.

Current status:

```
✅ COMPLETE   W1: Flight Delay → transfer misconnection recovery (+ feedback loop)
✅ COMPLETE   W2: Gate Change (bag divert + crew reassign)
✅ COMPLETE   W3: Cancellation (rebook + off-load + notify)
✅ COMPLETE   W4: Equipment Failure (reroute + maintenance alert + re-triage)
✅ COMPLETE   W5: Loading Failure at Origin (emergency load or rebook)
✅ COMPLETE   W6: Crew Shortage (adjacent-zone crew pull)
✅ COMPLETE   W7: Security Hold (HITL gate — cleared/rejected)
✅ COMPLETE   W8: Network Cascade (joint CP-SAT across multiple inbounds)
```

---

## Workflow 1 — Flight Delay (✅ complete + feedback loop closed)

**Trigger:** `FlightDelayed(flight_id, delay_minutes)`

```
Get at-risk connecting bags (Tier 0)
      ↓
Slack triage per bag: slack = window − move_time (Tier 1)
      ↓
Contention check: recoverable > crew_capacity? (Tier 1)
      ↓
CP-SAT if contended — optimal subset to save (Tier 2)
      ↓
Dispatch: exception routing + ramp task + AT_RISK notify (Tier 1)
          OR mark missed + MISSED notify (Tier 1)
      ↓
(Future) Wait for confirming scan — did the bag actually make it?
```

**Feedback loop:** `close_loop` node runs after `route_bags`. Calls
`BHSTool.confirm_bag_loaded()` (simulated scan), marks bag as `CONFIRMED_LOADED`,
sends `RECOVERED` notification. In production this node would be event-driven
(waiting for a real BHS scan message) rather than calling it synchronously.

---

## Workflow 2 — Gate Change (✅ complete)

**Trigger:** `GateChanged(flight_id, old_gate, new_gate)`

**Implemented in** `gate_change_coordinator.py`.

**Steps implemented:**

```
Identify bags already sorted to old_gate chute (Tier 0 BHS query)
      ↓
Re-route bags to new_gate via BHS divert command (Tier 1 — lookup table)
      ↓
Identify crew/equipment assigned to old_gate (Tier 0)
      ↓
Reassign crew/equipment to new_gate (Tier 1 rule: closest available crew)
      ↓
Update load plan gate field (Tier 1)
      ↓
Notify gate agents at both old and new gate (Tier 1)
      ↓
Notify connecting passengers if new gate changes their walk time significantly (Tier 1)
```

**New tools needed:**
- BHS divert command (`BHSTool.divert_to_gate(bag_tags, new_chute)`)
- Gate distance lookup (is the new gate same terminal or requires tug?)

**Tier needed:** All Tier 1 (rule-based lookups). No optimization, no LLM.

---

## Workflow 3 — Flight Cancellation (🟡 partial)

**Trigger:** `FlightCancelled(flight_id, reason)`

**What happens today:** Playbook fires → baggage + dispatch + comms
activate. BaggageCoordinator runs triage with delay=999 (all bags missed).
Bags marked missed. Passengers notified. No rebooking.

**What the full workflow should do:**

```
Find all passengers on cancelled flight (Tier 0)
      ↓
Find all bags checked in for that flight (Tier 0)
      ↓
Find next available flights to same destinations (Tier 0 — schedule query)
      ↓
Group passengers by destination (Tier 1)
      ↓
Rebook passengers on next available (Tier 1 — capacity check, priority rules)
      ↓
Rebook bags to match new flights (Tier 1)
      ↓
For bags already loaded: initiate off-load (Tier 1 → ramp task)
      ↓
Update load plans on affected flights (Tier 1)
      ↓
Notify all passengers: cancellation + rebooking confirmation (Tier 1)
```

**New tools needed:**
- Schedule query tool (`schedule.find_next_flight(origin, destination, after_time)`)
- Rebooking tool (`reservation.rebook_passenger(pnr, new_flight)`)
- Off-load command (`BHSTool.initiate_offload(bag_tags, flight_id)`)

**Tier needed:** Entirely Tier 1 once the data is available. The rebooking
prioritisation (VIP first, fewest connections, etc.) may benefit from a cost
function — but not an LLM.

---

## Workflow 4 — Equipment Failure (✅ complete)

**Trigger:** `EquipmentFailed(equipment_id, zone, failure_type)`

Examples: conveyor belt failure, CT scanner down, sort chute jammed.

**What the workflow should do:**

```
Identify which bags are currently on or queued for the failed equipment (Tier 0)
      ↓
Classify: which bags can be rerouted via alternate BHS path? (Tier 1)
      ↓
Issue BHS reroute commands for alternate path (Tier 1)
      ↓
Identify bags with no alternate path (manual handling required) (Tier 1)
      ↓
Estimate delay introduced per bag from the failure (Tier 1 — timing math)
      ↓
Re-run triage for bags whose connection is now at risk due to delay (Tier 1)
      ↓
If new at-risk bags found: → Delay Workflow (reuse existing) (Tier 1)
      ↓
Dispatch manual handling crew for bags with no alternate path (Tier 1)
      ↓
Alert maintenance for equipment repair (Tier 1)
```

**Implemented in** `equipment_coordinator.py`. `EQUIPMENT_FAILURE` playbook registered.

**Why this is different from a delay:**
A delay hits all bags on one inbound flight. An equipment failure hits all bags
in a zone, regardless of which flight they came from. The trigger is physical
infrastructure, not flight schedule.

**New tools needed:**
- Equipment status tool (`equipment.get_affected_bags(zone)`)
- BHS alternate path tool (`bhs.find_alternate_route(bag_tag, failed_zone)`)
- Maintenance alert tool (`maintenance.raise_alert(equipment_id)`)

**Tier needed:** Tier 1 throughout. The alternate path selection could be
pre-computed as a lookup table (BHS topology is fixed). No LLM.

---

## Workflow 5 — Loading Failure at Origin (✅ complete)

**Trigger:** `BagNotLoaded(bag_tag, flight_id)` detected at departure

This is the **second biggest cause of mishandling (16%)** — a bag that was
checked in but never physically loaded. Detected when the departure scan shows
it missing from the hold manifest.

**What the workflow should do:**

```
Confirm bag not loaded (departure manifest check) (Tier 0)
      ↓
Locate bag in BHS (where did it end up?) (Tier 0)
      ↓
Is flight still at gate (or recent departure)? (Tier 0 — AODB check)
      ↓
If still at gate AND enough time: initiate emergency load (Tier 1)
      ↓
If departed: find next flight to destination (Tier 0 — schedule query)
      ↓
Book bag on next flight (Tier 1)
      ↓
Update passenger (MISSED + delivery ETA on next flight) (Tier 1)
      ↓
File mishandled bag report for measurement (Tier 1)
```

**Why this isn't triggered today:**
Our system only handles events that arrive when a delay is detected. A loading
failure is detected at a different point in the process (departure check, not
arrival). It needs a different event source — the departure manifest system, not
the AODB delay feed.

**New tools needed:**
- Manifest verification tool (`load_plan.verify_bags_loaded(flight_id)`)
- Emergency load dispatcher (`ramp.emergency_load(bag_tag, flight_id)`)

**Tier needed:** Tier 1 — pure decision rules once the data is present.

---

**Implemented in** `loading_failure_coordinator.py`. `BAG_NOT_LOADED` playbook registered.

---

## Workflow 6 — Ramp Crew Shortage (❌ not built)

**Trigger:** `CrewShortage(zone, available_crew, required_crew)` or
detected implicitly when RampCoordinator escalates repeatedly.

**What the workflow should do:**

```
Assess how many exception tasks are queued (Tier 0)
      ↓
Check crew availability in adjacent zones (Tier 0)
      ↓
If adjacent crew available: pull crew from adjacent zone (Tier 1)
      ↓
Update crew status in both zones (Tier 1)
      ↓
Re-run CP-SAT optimizer with updated capacity (Tier 2)
      ↓
If no crew available at all: escalate to human AOCC officer (Tier 1)
      ↓
Re-prioritise which bags get manual handling vs auto-defer (Tier 1)
```

**Tier needed:** Tier 1 for crew reallocation rules, Tier 2 for re-optimising
under new capacity. No LLM.

---

## Workflow 7 — Security Hold on a Bag (❌ not built)

**Trigger:** `SecurityHold(bag_tag, reason)` from CT scanner or TSA flag.

**What the workflow should do:**

```
Mark bag as SECURITY_HOLD status (Tier 0 write)
      ↓
Notify baggage service agent (Tier 1)
      ↓
Pull bag from BHS queue — prevent it from loading (Tier 1)
      ↓
Notify passenger: bag held for inspection, will travel on next available (Tier 1)
      ↓
Remove bag from load plan (Tier 1)
      ↓
Wait for security clearance or rejection (external — human in loop)
      ↓
On clearance: rebook on next flight if original departed (Tier 1)
      ↓
On rejection: hand off to law enforcement protocol (Tier 1 → human)
```

**What makes this different:** It's primarily a compliance and handoff workflow,
not an optimisation one. The system's job is to notify the right people and prevent
the bag from loading — not to make a creative decision about it.

**Tier needed:** Tier 1 throughout. Human-in-loop at the clearance decision.

---

## Workflow 8 — Network Cascade Detection (✅ complete)

This is the most complex remaining workflow. It doesn't respond to a single event;
it watches a pattern of events forming across the hub.

**Trigger:** Pattern — multiple delay events in a short window affecting
the same outbound bank (e.g. three inbounds all delayed → same outbound flight
getting 20+ transfer bags at risk simultaneously).

**What the workflow should do:**

```
Detect: N inbound delays all affecting same outbound (Tier 1 — count/threshold)
      ↓
Aggregate all at-risk bags across all inbounds (Tier 0)
      ↓
Run triage once across the combined set (Tier 1)
      ↓
Run CP-SAT across the combined set with shared crew constraint (Tier 2)
      ↓
Assess: should the outbound be held? (Tier 1 — combined cost model)
      ↓
Assess: will holding the outbound cascade further delays downstream? (Tier 1)
      ↓
Dispatch coordinated plan (Tier 1)
```

**Implemented in** `network_cascade_coordinator.py`. `NETWORK_CASCADE` playbook fires on
`COMPOUND` events with ≥ 2 `affected_flights`.

**Why this is not just three separate delay workflows:**
Separate per-inbound delay workflows each assume full crew capacity. In a cascade they
compete for the same ramp crew. The joint CP-SAT run sees all bags and the true shared
constraint, producing one feasible plan rather than N infeasible independent ones.

---

## Workflow Selection — Where the LLM Earns Its Place

For the eight workflows above, the selection logic is simple enough to be a lookup
table (the playbook registry):

```python
FLIGHT_DELAY      → Workflow 1
GATE_CHANGE       → Workflow 2
CANCELLATION      → Workflow 3
EQUIPMENT_FAILURE → Workflow 4
BAG_NOT_LOADED    → Workflow 5
CREW_SHORTAGE     → Workflow 6
SECURITY_HOLD     → Workflow 7
```

No LLM needed for clean single-event dispatching.

**Where the LLM becomes useful** is Workflow 8 (network cascade) and for
compound events that combine multiple types simultaneously:

```
Flight delayed 45 min
+ Belt failure in Zone B
+ Only one crew team operational
```

None of the eight workflows above covers this combination. The LLM's job is:

```text
This requires:
  Workflow 1 (delay recovery)
  Workflow 4 (equipment failure)
  Workflow 6 (crew shortage)

Run them with shared crew constraint.
```

Then CP-SAT handles the joint optimisation with the combined resource constraint.

That is the correct, minimal role for the LLM: choosing which playbooks to
combine for a situation that could not be pre-written.

---

## Build Status

| Workflow | Status | Coordinator |
|---|---|---|
| W1: Flight Delay + feedback loop | ✅ Complete | `baggage_coordinator` + `close_loop` |
| W2: Gate Change | ✅ Complete | `gate_change_coordinator` |
| W3: Cancellation | ✅ Complete | `cancellation_coordinator` (rebook + offload + notify) |
| W4: Equipment Failure | ✅ Complete | `equipment_coordinator` |
| W5: Loading Failure | ✅ Complete | `loading_failure_coordinator` |
| W6: Crew Shortage | ✅ Complete | `ramp_coordinator` adjacent-zone pull |
| W7: Security Hold | ✅ Complete | `security_hold_coordinator` |
| W8: Network Cascade | ✅ Complete | `network_cascade_coordinator` |

## Remaining Work

| Item | What's needed |
|---|---|
| **Cancellation (W3)** | ✅ Done — `cancellation_coordinator` with `ScheduleTool` |
| **Crew Shortage (W6)** | ✅ Done — `ramp_coordinator` adjacent-zone pull |
| **Security Hold (W7)** | ✅ Done — `security_hold_coordinator` with HITL cleared/rejected gate |
| **Real data feed** | All workflows run on mock tools. Production value lands when real BHS scans and AODB events flow in. |
| **Measurement** | ✅ Done — `demo/replay.py`: 5 scenarios, +40% bags recovered, 2.5s vs ~3 min manual |
