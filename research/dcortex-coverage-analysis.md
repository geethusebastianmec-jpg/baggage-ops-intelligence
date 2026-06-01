# dCortex Coverage Analysis — What They Claim vs What We Built

## dCortex's Actual Problem Statement (from dcortex.ai)

> "The System of Action for Airlines, Transportation & Logistics.
> AI agents that reason, coordinate, and act across operations in real time.
>
> Millions of people spend their lives coordinating the operations that keep the
> world moving. Behind every on-time departure, shipment, and timely delivery,
> are teams managing enormous complexity across systems that were never designed
> for the scale and speed modern operations demand.
>
> Entire industries continue to operate under constant pressure while struggling
> with thin margins, fragmented systems, and growing coordination overhead.
>
> We are building a System of Action for complex enterprise operations. It reasons,
> coordinates, and acts across existing operational environments without requiring
> organizations to rebuild the systems they already depend on."

### Their three product claims

| Claim | What they mean |
|---|---|
| **Reasons across every system** | Connects to existing tools. Orchestrates decisions WITHOUT human middleware. |
| **Acts, not just alerts** | Goes beyond dashboards. Executes resolutions, dispatches tasks, closes the loop. |
| **Built for critical operations** | Industry-specific rules, compliance requirements, real operational context. |

### Their three value propositions

| Value | What they mean |
|---|---|
| **Reliable** | Enterprise-grade. Consistent actions. Trusted outcomes. Always on. |
| **Explainable** | Not a black box. Every decision and action auditable. Trace to origin. |
| **Scalable** | 500+ concurrent agents. Zero downtime. Cloud and model agnostic. |

---

## What "System of Action for Airlines, Transportation & Logistics" Covers

Their stated scope is three verticals — not just airlines:

**Airlines** (their first stated vertical):
- Irregular operations (IROPS): delays, cancellations, diversions
- Baggage coordination and transfer misconnection recovery ← what we built
- Crew scheduling and recovery
- Aircraft turnaround (fueling, cleaning, catering, boarding, baggage — coordinated)
- Gate management
- Passenger rebooking and service recovery
- Ground service provider (GSP) coordination

**Transportation** (second vertical):
- Freight / trucking dispatch
- Rail operations
- Port logistics and vessel turnaround

**Logistics** (third vertical):
- Warehouse coordination
- Last-mile delivery
- Supply chain disruption management

We built one sub-domain of one of three verticals.

---

## How We Match Each dCortex Claim

### ✅ "Acts, not just alerts"

**Their claim:** Goes beyond dashboards. Executes resolutions, dispatches tasks, closes the loop.

**Our implementation:**
- Exception routing opened in BHS (bag physically redirected)
- Ramp crew task assigned (someone actually goes to get the bag)
- Load plan updated
- Passenger notified at each stage
- `close_loop` node: confirming BHS scan proves the bag physically made it
- MIP rerouter: missed bags assigned to actual rerouting flights

**Gap:** Our "acts" are still on mock tools. Real deployment requires actual BHS API calls, not simulated ones. The architecture is correct; the integrations are stubs.

---

### ✅ "Reasons across every system"

**Their claim:** Connects to existing tools and orchestrates decisions without human middleware.

**Our implementation:**
- Connects to: BHS, AODB, load planning, ramp dispatch, passenger comms (all mocked)
- Orchestrates: 8 disruption workflows across 4 domains in parallel
- No human middleware: supervisor activates coordinators autonomously

**Gap:** "Every system" for an airline includes crew scheduling (which affects who can physically move the bags) and revenue management (which affects which passengers have priority). We have neither.

---

### ✅ "Built for critical operations"

**Their claim:** Industry-specific rules, compliance requirements, real operational context.

**Our implementation:**
- $150/bag miss cost, $500/min hold cost — real industry numbers
- 25-minute minimum connection time at JFK
- Zone-based move time (8 min Zone B, 26 min Zone D) — realistic
- Security hold coordinator with HITL gate and compliance log
- 8 playbooks for 8 known disruption types
- Audit trail: every action logged to Kafka with full decision chain

**Gap:** "Compliance requirements" likely includes aviation regulatory requirements (ICAO, IATA, local airport authority) that we haven't formally mapped.

---

### ✅ "Explainable"

**Their claim:** Not a black box. Every decision and action traceable to its origin.

**Our implementation:**
- Tier 1 triage: `slack = window - move_time` — exact arithmetic, fully auditable
- CP-SAT: deterministic solver, same inputs always same output
- MIP: optimal rerouting with printable LP solution
- LLM: only 20% of events, only for routing decisions (never computes answers)
- Kafka audit topic: every action logged with node name, inputs, result, timestamp
- "Trace any decision back to its origin" — we have this via Kafka replay

**Gap:** None significant. This is one of our strongest points.

---

### ✅ "Reliable"

**Their claim:** Consistent actions. Trusted outcomes. Always on.

**Our implementation:**
- Deterministic at T1 (arithmetic) and T2 (solver) — same inputs, same output
- LangGraph PostgreSQL checkpointer: agents resume from last node on crash
- Kafka retry with exponential backoff in the API consumer
- Graceful Kafka topic auto-creation on startup

**Gap:** No production HA deployment, no actual SLA, no load test results.

---

### ❌ "Scalable — 500+ concurrent agents. Zero downtime. Cloud and model agnostic."

**Their claim:** The system handles 500+ agents concurrently without downtime.

**Our implementation:**
- Architecture supports it (Kafka fan-out, ThreadPoolExecutor, stateless coordinators)
- 8 coordinator types, roughly 3-5 active per disruption event
- No load testing at the 500-agent level
- Not model agnostic: LLM calls are hardcoded to Gemini

**Gap:** Scale untested. Gemini lock-in. No HA deployment.

---

## Coverage of the Baggage Domain Specifically

Against dCortex's implied scope for airline baggage coordination:

| Problem | Our coverage |
|---|---|
| Transfer misconnection detection and recovery | ✅ Full (Tier 1 triage + CP-SAT + MIP) |
| Flight delay cascade | ✅ Full (8 workflows including network cascade) |
| Flight cancellation with bag rerouting | ✅ Full (MIP network flow rerouter) |
| Gate change with bag diversion | ✅ Full |
| Equipment failure in BHS | ✅ Full (reroute + maintenance alert) |
| Loading failure at origin | ✅ Full (emergency load or MIP rebook) |
| Crew shortage (ramp) | ✅ Full (adjacent-zone pull) |
| Security hold compliance | ✅ Full (HITL gate, compliance log) |
| Multi-inbound hub cascade (joint optimisation) | ✅ Full (joint CP-SAT) |
| Passenger notification lifecycle | ✅ Full (AT_RISK → RECOVERED → MISSED) |
| Confirming scan / feedback loop | ✅ Simulated (real would need BHS scan events) |
| Crew bag priority (crew deadheads) | ❌ Not built — crew bags have highest IATA priority |
| Revenue-class passenger priority | ❌ Only binary priority (1.0/2.0), not fare-class aware |
| GSP (ground service provider) coordination | ❌ Not modelled — outsourced handling is a real constraint |
| Interline bag coordination | ✅ InterlineCoordinator: IATA Type B alert, transfer desk, partner notification |
| GSP coordination | ✅ GSPTool: airline-direct vs Swissport/Menzies/dnata routing |
| Crew bag priority (IATA P1) | ✅ TicketClass.CREW=3.0, FIRST=2.4+, BUSINESS=1.9+, ECONOMY=1.0 |
| Revenue-class weighting | ✅ 13-entry PRIORITY_WEIGHTS table: ticket class × FF tier |
| Weight & balance integration | ❌ Load plan is mocked; real W&B is a separate system |
| Real BHS data feed | ❌ All tools are mocked — biggest production gap |
| Aircraft turnaround (beyond bags) | ❌ Fueling, catering, cleaning are outside scope |
| Crew scheduling impact on baggage | ❌ Not modelled (crew positioning affects capacity) |

---

## Coverage of Transportation & Logistics (Second and Third Verticals)

**Transportation** — 0% covered. Trucking, rail, port operations not built.

**Logistics** — 0% covered. Warehouse, last-mile, supply chain not built.

These are dCortex's stated verticals 2 and 3. Our system is entirely within vertical 1 (airlines), within that in one sub-domain (baggage). dCortex's $1T market claim comes from addressing all three verticals.

---

## What We Built vs What dCortex Claims to Build

### Where we are ahead of their stated claims

| Dimension | Our advantage |
|---|---|
| **Solver correctness** | We separate CP-SAT (resource assignment) from MIP (network flow). Most systems and papers don't apply this distinction to baggage specifically. |
| **Tier-based determinism** | T1 arithmetic → T2 solver → T4 LLM as last resort. dCortex's description doesn't specify this — they likely use LLM more broadly. |
| **Closed feedback loop** | `close_loop` + confirming scan is explicitly designed for production. Most demo systems skip this. |
| **8 disruption workflows** | Complete coverage of the disruption type space for baggage. No evidence dCortex has this depth for this sub-domain. |
| **Audit trail** | Kafka-based, fully replayable. Matches their "explainable" claim exactly. |

### Where dCortex's claim exceeds what we built

| Dimension | Their claim vs our gap |
|---|---|
| **"Without rebuilding existing systems"** | We have mock tools. Real connectors to SITA WorldTracer, AODB, BHS middleware are missing. |
| **"500+ concurrent agents"** | Architecturally plausible; untested and unproven. |
| **"Cloud and model agnostic"** | We're Gemini-locked for the LLM path. |
| **"Transportation & Logistics"** | Two full verticals we haven't touched. |
| **"Crew and revenue integration"** | Crew bags, fare-class priority not modelled. |
| **"Interline coordination"** | Not modelled. Represents ~30% of mishandled bags. |
| **"Real operational context"** | Our context is synthetic (seed data). Their claim requires real feeds. |

---

## Honest Summary

### What we've built

A technically correct, architecturally principled implementation of the **airline baggage coordination sub-domain** of dCortex's stated scope.

- Every decision is made at the correct tier (T1 rules / T2 solver / T4 LLM).
- All 8 disruption types in the baggage domain are handled end-to-end.
- The architecture matches dCortex's three claims: acts (not just alerts), reasons across systems, explainable.
- The solver split (CP-SAT for resource assignment, MIP for network flow) is more principled than published alternatives.

### What dCortex likely does differently

- **Broader scope**: Airlines (full: not just baggage), Transportation, Logistics.
- **Real integrations**: Actual BHS APIs, airline PSS systems, crew scheduling systems.
- **Learning component**: "Trained on industry-specific rules" suggests they learn from historical data, not just hand-coded playbooks.
- **Scale**: 500+ concurrent agents implies they've load-tested and proven it.

### The critical path from our prototype to their scope

1. **Real data feed** — One airline, one real BHS/AODB connection.
2. **Crew bag priority** — Extend priority model to IATA crew bag priority rules.
3. **Interline** — Cross-airline event model.
4. **Model agnosticism** — Swap LLM provider via config, not code.
5. **Verticals 2 & 3** — Transportation and logistics workflows.

The first item is the gate. Everything else is an extension of the architecture we already have.
