# Baggage Ops Intelligence — Explained From Scratch

This document is for someone who has never worked in aviation and has never
built an AI system. It explains the real-world problem, how the industry handles
it today, what we built, what was wrong with the first version, and what the
correct version looks like.

---

## Part 1 — The Real World Problem

### What happens to your bag when you fly?

When you check a bag at the airport, a label with a barcode is attached to it.
That label tells every system in the airport where your bag is supposed to go.

Your bag then travels on a network of conveyor belts called the **BHS (Baggage
Handling System)**. Think of it like a subway system for luggage — underground
tunnels, automated sorters, conveyor belts, and chutes that route each bag to
the correct departure gate.

When your flight lands, your bag gets taken off the plane, travels back through
the BHS, and lands on the correct baggage carousel for you to pick up.

### What is a "connecting flight" and why do bags miss them?

A connecting flight means you fly from City A to City B, then get on a different
plane to go to City C. You buy both flights as one ticket.

When you do this, your bag is **checked all the way through to City C**. You
never touch it at City B. The airline is responsible for moving your bag from the
first plane to the second plane while you walk through the terminal.

Here is the problem: **the first flight is often late.**

When Flight AA401 from Chicago arrives 32 minutes late at JFK, your bag has only
25 minutes to physically travel from that arriving plane's hold, through the BHS,
across the terminal, and into the hold of Flight AA501 to London — before AA501
closes its doors and pushes back.

If nobody acts fast enough, your bag misses the connection and you land in London
without it. The airline then has to locate your bag, put it on the next flight to
London (which may be 8 hours later), and arrange delivery to your hotel. This
costs the airline roughly **$150 per bag** in recovery costs.

### How big is this problem?

- **33 million bags** are mishandled globally every year
- **$5 billion per year** in costs to airlines
- **41% of all mishandled bags** are due to transfer misconnections — exactly
  the scenario above
- The other big cause is **loading failures** (16%) — a bag that was never put
  on the plane in the first place

### Who fixes it today?

There is a room in every major airline's operations centre called the **AOCC
(Airline Operations Control Centre)**. It looks like a NASA mission control
room — dozens of screens, flight data everywhere, people on phones.

One of the jobs in that room is the **baggage coordination job**. When Flight
AA401 is delayed, a human coordinator:

1. Calls baggage services: "AA401 is 32 minutes late, check for connecting bags"
2. Calls ramp operations: "Can you get a crew to rush bags from AA401 to AA501?"
3. Calls dispatch: "Should we hold AA501 or let it go?"
4. Calls customer communications: "Notify passengers on AA401 who are connecting"

Each of those phone calls takes 1–3 minutes. By the time all four calls are done,
the window is often gone. A human coordinator doing this one phone call at a time
is the root cause of many missed connections.

---

## Part 2 — What We Built

### The core idea

Replace those four phone calls with one automated system that makes all four
decisions simultaneously, in under 2 seconds.

When Flight AA401's delay is detected, the system:
1. Instantly queries the BHS to find every bag on AA401 that has a connecting flight
2. Calculates which bags can physically make their connections (pure math — see below)
3. Decides what to do with each one: rush it, rebook it, or flag it as missed
4. Simultaneously dispatches instructions to ramp crew, updates the load plan,
   and sends text messages to affected passengers

This is what "multi-agent coordination" means in this context: multiple specialist
systems acting in parallel on the same problem.

### What is an "agent" here?

The word "agent" is overused in AI. In this system, it means something specific:

**An agent is a piece of software that:**
1. Reads the current state of the world (what flights are delayed, where are the bags)
2. Decides what actions to take based on rules, math, or reasoning
3. Executes those actions (notifies crew, updates systems)
4. Reports what it did (for the audit trail)

We have several specialised agents:

- **Baggage Coordinator** — decides which bags are at risk and what to do with them
- **Ramp Coordinator** — decides how to assign ground crew for the physical move
- **Dispatch Coordinator** — decides whether to hold the outbound flight or let it depart
- **Comms Coordinator** — decides which passengers to notify and what to tell them

All of these activate at the same time when a disruption event arrives.

### What is the "Strategic Supervisor"?

Above the domain coordinators sits a **Strategic Supervisor** — think of it as
the shift manager in the AOCC. It:

- Watches all incoming disruption events
- Matches each event to a pre-written playbook (for known disruption types)
- Activates the right domain coordinators in parallel
- Arbitrates if two coordinators give conflicting instructions

For example: the Baggage Coordinator says "hold AA501 — we can get 5 bags on in
time." The Dispatch Coordinator says "depart — we're already late." The Strategic
Supervisor resolves that conflict using a cost model.

---

## Part 3 — The Two Versions

### Version 1 (What We Built First) — and What Was Wrong With It

In Version 1, the **Baggage Coordinator** used an **LLM (Large Language Model)**
— the same type of AI that powers ChatGPT — to decide which bags were recoverable.

It sent Gemini a message like:

> "Flight AA401 is delayed 32 minutes. Flight AA501 departs in 25 minutes.
> 7 bags need to connect. Ramp crew is available.
> Which bags can make it? Return RECOVERABLE, PARTIAL, or UNRECOVERABLE."

Gemini would reply with something like:
> "PARTIAL. BA-001 through BA-005 are recoverable. BA-006 and BA-007 cannot
> make it because the queue position is too far."

**This was wrong for several reasons:**

#### 1. It used an expensive tool to answer a free question

The question "can this bag make it?" is arithmetic:
```
slack = minutes_until_outbound_closes − minutes_needed_to_physically_move_bag
if slack >= 0: YES, it can make it
if slack < 0:  NO, it cannot
```
That is a subtraction problem. You do not need an AI that costs money per call,
takes 1–3 seconds to respond, and occasionally hallucinates, to do subtraction.

#### 2. The answer was non-deterministic

Ask the same LLM the same question twice and you can get different answers.
In aviation operations, the decision "which bags are we saving?" must be the same
every time for the same inputs. You cannot explain to an airline operations team
that the system made a different call this morning than yesterday because the AI
"felt differently."

#### 3. It was unauditable

If something goes wrong — a bag misses a flight and a passenger complains — the
airline's operations team needs to trace exactly why that decision was made. An
LLM response is not auditable. "Gemini said so" is not a satisfying answer
when a passenger is demanding to know why their luggage ended up in the wrong city.

#### 4. It confused MCT with bag move time

**MCT (Minimum Connection Time)** is the total time a passenger needs to connect —
walking from one gate to another, going through customs if needed, boarding.
At JFK it is 60–90 minutes. This is irrelevant for bags. Bags do not walk.

**Physical bag move time** is how long it takes a ramp crew to move a bag from
one aircraft's hold to another via the tug and ramp lanes. This is 8–22 minutes
depending on how far apart the gates are and where in the BHS queue the bag is.

Version 1 used the MCT number in its reasoning (because that was what was in the
seed data), which would have dramatically under-saved bags that could physically
make it in 15 minutes.

---

### Version 2 (The Correct Architecture)

Version 2 replaces the LLM in the Baggage Coordinator with the correct tools for
each question. Here is the tier ladder:

```
QUESTION                                    TOOL USED           TIER
────────────────────────────────────────────────────────────────────
Where is bag X right now?                   Database read        0
Is this bag at risk? (slack math)           Plain Python code    1
Who gets notified?                          Lookup table         1
Is there crew contention?                   Simple count         1
Which bags to save under scarce crew?       CP-SAT solver        2
Which coordinators does this need?          Agent loop           3
Truly novel, never-seen disruption?         LLM                  4
```

**Tier 0** — reading the state of the world from the BHS, AODB (flight times),
and ramp crew systems. Already existed. Nothing to build.

**Tier 1** — deterministic rules. For each bag: `slack = window − move_time`.
If slack ≥ 0 → recoverable. Instant, free, always the same answer. Also handles
the dispatch decision: `bags_saved × $150 vs hold_time × $500` — pure comparison.

**Tier 2** — the CP-SAT solver. This runs only when there is **resource contention**:
more bags need to be rushed than the ramp crew can handle simultaneously. In that
case, we need to find the *optimal subset* — which bags do we save to minimise the
total cost of misses? CP-SAT (a constraint solver from Google's OR-Tools library)
finds the exact optimal answer in under 100 milliseconds for our scale. No LLM.

**Tier 3** — the agent (coordinator). Its only job is to sequence the steps above
and adapt if one fails. If the ramp crew system is unavailable, the coordinator
retries with a different crew zone. This retry-on-failure behaviour is the one
genuinely "agentic" part. Everything else is deterministic.

**Tier 4** — the LLM. Kept in the **Strategic Supervisor**, where it belongs.
The supervisor uses an LLM only for genuinely novel disruptions that cannot be
matched to a pre-written playbook — for example, a simultaneous crew shortage,
weather event, and mechanical failure at the same hub. Even there, the LLM's
job is to decide which coordinators to activate, not to compute anything.

---

## Part 4 — A Worked Example (Version 2)

**Scenario:** AA401 arrives at JFK 32 minutes late. AA501 to London departs in
25 minutes. 7 bags need to connect.

**Step 1 — Triage (Tier 1 math):**

```
Bag     BHS Location   move_time   slack = 25 − move_time   Decision
BA-001  Zone B          8 min       +17 min                  RUSH ✅
BA-002  Zone B          8 min       +17 min                  RUSH ✅
BA-003  Zone B          8 min       +17 min                  RUSH ✅
BA-004  Zone B          8 min       +17 min                  RUSH ✅
BA-005  Zone C         12 min       +13 min                  RUSH ✅
BA-006  Zone D         22 min        +3 min                  UNRECOVERABLE ❌
BA-007  Zone D         22 min        +3 min                  UNRECOVERABLE ❌
```

BA-006 and BA-007 are physically 22 minutes from the gate. The window is only
25 minutes. With 3 minutes of slack and the ramp crew needing to sprint them
across the terminal, it is not physically achievable. This is not an LLM judgment —
it is a fact about where those bags are.

**Step 2 — Contention check (Tier 1 count):**
5 recoverable bags, crew capacity = 4 crew × 3 bags each = 12 simultaneous.
5 < 12 → no contention. CP-SAT not needed. Route all 5 directly.

**Step 3 — Dispatch decision (Tier 1 cost comparison):**
5 bags saved × $150 = $750 in avoided recovery costs.
Hold would take 3 minutes × $500/min = $1,500 in delay costs.
$750 < $1,500 → DEPART. (If we had 20 recoverable bags: 20 × $150 = $3,000 > 1,500 → HOLD.)

**Step 4 — Dispatch (Tier 1 lookup table):**
- RUSH on BA-001 to BA-005 → ramp crew + exception routing + AT_RISK notify
- UNRECOVERABLE on BA-006, BA-007 → mark as MISSED + MISSED notify to passengers

**Total time for this decision:** under 2 seconds. No LLM call in the hot path.

---

## Part 5 — What Stays the Same

The **Strategic Supervisor** still uses the LLM for what it is actually good at:

- A flight is delayed AND its crew is sick AND there is a ground stop due to weather.
  Three simultaneous events. No pre-written playbook covers this combination.
  The LLM looks at the situation and decides: "Activate baggage coordinator,
  dispatch coordinator, and comms coordinator. Skip ramp coordinator — no crew available."
  That routing decision involves reading the situation and making a judgment about
  what needs attention. Language-model-shaped reasoning. Correct Tier 4 use.

The LLM is still part of the system. It is just no longer doing subtraction.

---

## Summary — V1 vs V2

| Aspect | Version 1 | Version 2 |
|---|---|---|
| Feasibility decision | Gemini LLM (non-deterministic, slow, costly) | Deterministic arithmetic — `slack = window − move_time` |
| Contention handling | LLM guess at which bags to save | CP-SAT optimal solver — exact, milliseconds |
| Dispatch hold/depart | LLM for "ambiguous" cases | Cost comparison: `bags_saved × $150 vs hold × $500` |
| Bag move time | Used MCT (~60 min) — wrong concept | Per-bag physical move time (8–22 min based on BHS zone) |
| Auditability | "The LLM said so" | Exact inputs → exact outputs, logged |
| LLM role | Hot path — every bag decision | Rare path — only novel compound disruptions at the supervisor level |
| Test approach | Mock the LLM, assert on its mock response | No mocking needed — deterministic inputs produce deterministic outputs |
| Speed | 1–3 seconds per LLM call × 3 calls | <100ms total for triage + CP-SAT |

The architecture is not simpler because we removed AI. It is more correct because
each question is answered by the tool that was designed to answer it.
