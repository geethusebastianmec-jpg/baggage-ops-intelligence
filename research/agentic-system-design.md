# Agentic System Design for Airline Baggage Coordination

## 1. The Problem We Are Actually Solving

Before choosing any architecture, the problem must be stated precisely.

The baggage coordination failure is not a data problem or a tracking problem. It is a **cross-domain, time-critical, interdependency problem**. When a flight delay arrives:

- The ramp crew needs to know which transfer bags are at risk
- The load planner needs to update weight/balance docs before departure
- The baggage service agent needs to open exception routing for at-risk bags
- The departure controller needs to know whether holding is worth it
- The passenger notification system needs to fire before the passenger panics at the carousel

All of this must happen **simultaneously**, across **separate operational systems**, in **under 3 minutes** — the window before a connection becomes unrecoverable. Today, a human coordinator sits in the AOCC doing this manually, one phone call at a time.

The system we are designing must replace that manual coordination with autonomous, real-time, multi-domain action.

---

## 2. The Design Space — All Patterns Evaluated

### 2.1 Pattern Taxonomy

| Pattern | Coordination Model | Execution Model | Adaptability | Latency | Debuggability |
|---|---|---|---|---|---|
| **Pipeline** | Sequential chain | Step-by-step | Low | Sum of stages | Excellent |
| **Router** | Classifier dispatches | Independent parallel | Low | Near-zero | Good |
| **Supervisor** | Central orchestrator delegates | Parallel workers | Medium | Medium | Good |
| **Swarm** | Peer-to-peer, no controller | Emergent parallel | High | Low | Poor |
| **Hierarchical** | Multi-tier tree (strategy → domain → execution) | Parallel per tier | High | Medium | Good |
| **ReAct** | Single agent iterative loop | Sequential observe-reason-act | Highest | High (token cost) | Medium |
| **Plan-Execute** | Upfront planner + executor | Sequential execution | Low-Medium | Medium | Good |
| **Graph (DAG)** | Dependency graph, parallel where possible | Parallel by dependency | Medium | Lowest (3.6x faster than ReAct) | Medium |
| **Event-Driven** | Reactive subscription model | Parallel, decoupled | High | Lowest (reactive) | Poor without tooling |

### 2.2 Why Each Pattern Alone Fails for Baggage

**Pipeline** — Baggage events are not sequential. When a delay hits, ramp notification and load plan update are independent and both urgent. Sequential execution costs lives (minutes).

**Router** — Routes tasks to individual handlers, but cannot coordinate *between* handlers. Ramp and load planning agents would receive separate tasks with no shared awareness that both are part of the same disruption event.

**Pure Supervisor** — One orchestrator becomes a bottleneck. During IROPS (irregular operations), the system receives dozens of cascading events per minute. A single supervisor reasoning over all of them sequentially cannot keep up.

**Pure Swarm** — No global state. The transfer bag problem requires knowing the full picture: which flights are delayed, which bags are on those flights, which connection windows are at risk, and which ramp crews have capacity. A swarm with only local peer visibility misses this. Also: poor debuggability is disqualifying for aviation where audit trails are required.

**ReAct (single agent)** — Generates a new plan after every observation. Under a disruption with 12 interdependent events firing in 4 minutes, this becomes computationally unaffordable and too slow. 1500–2500ms per reasoning cycle multiplied across concurrent disruptions breaks the time window.

**Plan-Execute** — Plans become stale in seconds during IROPS. An upfront plan generated when a flight is 20 minutes late is invalid when it becomes 40 minutes late 90 seconds later. Cannot handle dynamically changing ground truth.

**Pure Graph/DAG** — Excellent for known workflows with stable dependency structures. Fails when the dependency graph itself changes mid-execution (e.g., a second disruption hits during execution of the first recovery plan).

**Pure Event-Driven** — Solves the latency and decoupling problem but sacrifices global coherence. Without a coordinator aware of the full state, two domain agents could make conflicting decisions (e.g., ramp agent decides to off-load bags while dispatch agent decides to hold the flight — both valid locally, contradictory globally).

---

## 3. The Chosen Architecture

### Event-Driven Hierarchical Supervisor with DAG Execution at Domain Level

This is a hybrid of three patterns, each applied at the tier where it is most effective:

```
┌─────────────────────────────────────────────────────┐
│         TIER 1 — Operations Intelligence Layer       │
│  (Strategic Supervisor + ReAct for novel scenarios)  │
│                                                      │
│   • Monitors full operational state                  │
│   • Detects emerging disruptions                     │
│   • Decides which domain coordinators to activate    │
│   • Resolves cross-domain conflicts                  │
└─────────────────┬───────────────────────────────────┘
                  │  Events + Activation Signals
          ┌───────▼──────────────────────────────┐
          │          EVENT BUS (Kafka-style)       │
          │  All operational events flow through   │
          │  Agents subscribe to relevant topics   │
          └────┬──────────┬──────────┬────────────┘
               │          │          │
    ┌──────────▼──┐  ┌────▼──────┐  ┌▼──────────────┐
    │  TIER 2     │  │  TIER 2   │  │  TIER 2        │
    │  Baggage    │  │  Ramp     │  │  Dispatch      │
    │  Coordinator│  │  Coord.   │  │  Coordinator   │
    │  (DAG exec) │  │ (DAG exec)│  │  (DAG exec)    │
    └──┬──────────┘  └────┬──────┘  └────────────────┘
       │                  │
  ┌────▼────┐       ┌─────▼─────┐
  │TIER 3   │       │TIER 3     │
  │BHS Query│       │Crew Notify│
  │Load Plan│       │Equipment  │
  │Passenger│       │Gate Status│
  │Comms    │       │Ramp Alloc │
  └─────────┘       └───────────┘
```

---

## 4. Each Tier in Detail

### Tier 1 — Operations Intelligence Layer (Strategic Supervisor)

**Role:** The only agent with a global view. Reads the full operational picture continuously. Detects when a pattern of events constitutes an emerging disruption, classifies its severity and domains affected, and activates the relevant domain coordinators with a shared context packet.

**Thinking model:** Hybrid ReAct + Plan-Execute
- For known disruption patterns (SLOT delays, weather cancellations, gate swaps): fires a predetermined playbook — fast, predictable, no token overhead from reasoning from scratch
- For novel or compound disruptions (simultaneous crew shortage + weather + connecting bank): invokes a ReAct loop to reason through dependencies before activating domains

**Critical responsibility:** Cross-domain conflict resolution. If the Ramp Coordinator wants to off-load bags from a flight and Dispatch Coordinator wants to hold it, Tier 1 arbitrates using the global cost model (delay cost vs. mishandled bag cost vs. network cascade cost).

**Does NOT do:** Execute any operational task directly. It only coordinates and arbitrates.

---

### Tier 2 — Domain Coordinators (Event-Driven + DAG Execution)

One coordinator per operational domain:

| Coordinator | Owns | Subscribes To |
|---|---|---|
| **Baggage Coordinator** | BHS routing, exception handling, carousel assignment, passenger bag tracking | Flight delay events, gate change events, transfer manifest updates |
| **Ramp Coordinator** | Ground crew allocation, tug/belt loader assignment, aircraft hold management | Baggage exception events, departure hold events, equipment status |
| **Dispatch Coordinator** | Flight release, load plan sign-off, departure authorization | Load plan change events, crew ready events, baggage clear events |
| **Customer Comms Coordinator** | Passenger SMS/app notifications, carousel announcements | Bag delay events, carousel assignment events, arrival confirmations |
| **Equipment Coordinator** | Conveyor belt status, scanner health, predictive maintenance alerts | Equipment sensor streams |

**Execution model within each coordinator: DAG**

When a domain coordinator is activated, it builds a dependency graph of the tasks it must execute, identifies which are independent, and runs them in parallel. Example for Baggage Coordinator on a transfer disruption event:

```
Event: Flight A delayed 25 min. 8 bags transferring to Flight B. Window = 22 min.

DAG:
  [Query BHS for bag locations]  ──────────┐
  [Pull Flight B departure status] ────────┤──► [Calculate recovery feasibility]
  [Get ramp crew availability] ────────────┘         │
                                               ┌──────▼────────┐
                                               │ Feasible?      │
                                             Yes              No
                                               │               │
                                    [Initiate           [Flag bags as
                                     exception           at-risk, notify
                                     routing]            Dispatch + Tier 1]
                                               │
                               [Notify ramp] [Update load plan] [Notify passenger]
                               (parallel)    (parallel)         (parallel)
```

This DAG approach gives **3.6x speed** over sequential execution for the same set of tasks, and the parallelism is exactly what the transfer window demands.

---

### Tier 3 — Execution Agents (Tool-Use Agents)

Fine-grained, stateless agents that wrap real operational systems. Each does one thing:

| Agent | Action | System It Calls |
|---|---|---|
| BHS Query Agent | Pull bag location/status by tag | SITA WorldTracer / BHS API |
| Load Plan Agent | Read/write aircraft load documents | Dispatch system API |
| Ramp Notify Agent | Send task to ramp crew via radio/tablet | Ground ops system |
| Passenger Notify Agent | Trigger SMS/app push with bag status | Airline app / SMS gateway |
| RFID Scanner Agent | Query RFID read events for specific tags | Airport RFID middleware |
| Equipment Health Agent | Read conveyor/scanner sensor telemetry | Predictive maintenance platform |
| Gate Status Agent | Get current gate assignment for a flight | AODB (Airport Operations Database) |

These agents are dumb on purpose. All reasoning lives in Tier 1 and Tier 2. Tier 3 agents are purely I/O wrappers that can be swapped when airports change systems.

---

## 5. The Event Bus — Why It Is Structural, Not Optional

The event bus is the architectural spine. Without it, the system degrades to a polling architecture where every agent must continuously ask "has anything changed?" — wasting cycles and adding latency.

With an event bus:
- A flight delay message lands in the AOCC system → published to the bus
- Every subscribed agent reacts within milliseconds, in parallel, without polling
- The event log serves as a complete audit trail for every action taken (critical for aviation incident reporting)
- Replay capability: if an agent crashes mid-execution, it can replay from the event log and resume

**Topic structure:**
```
ops.flights.delays
ops.flights.gate-changes
ops.baggage.exceptions
ops.baggage.carousel-assignments
ops.ramp.crew-status
ops.equipment.alerts
ops.decisions.conflicts   ← Tier 1 arbitration outputs
ops.decisions.playbooks   ← Tier 1 playbook activations
```

---

## 6. Memory Architecture

Agents at different tiers need different memory:

| Memory Type | Used By | Content | Retention |
|---|---|---|---|
| **Operational state** (working memory) | All tiers | Current flight statuses, active disruptions, bag locations | Session (real-time operation) |
| **Episodic memory** | Tier 1 | Past disruption patterns and outcomes, what worked and what didn't | Persistent — used for playbook improvement |
| **Semantic memory** | Tier 2 | Domain rules: connection time minimums, off-loading constraints, SLA thresholds | Persistent — updated via configuration |
| **Procedural memory** | Tier 1 | Playbooks for known disruption types | Persistent — updated by ops team + learning |

---

## 7. Human-in-the-Loop Design

For aviation, full autonomy is not the initial target. The system is designed with three operating modes:

| Mode | System Role | Human Role |
|---|---|---|
| **Advisory** | Surfaces recommendations + predicted outcomes | Approves every action before execution |
| **Semi-autonomous** | Executes low-risk actions (passenger notifications, carousel assignments) autonomously; escalates high-stakes decisions | Approves hold/off-load decisions, cross-domain conflicts |
| **Full autonomous** | Executes all actions within pre-authorized playbooks; escalates only novel scenarios | Monitors, can override at any time |

Airline operations start in Advisory mode, build trust, then progressively shift to Semi-autonomous as the system proves accuracy. Full autonomous is the long-term target for routine disruptions.

---

## 8. Tradeoff Analysis — Why This Over the Alternatives

### Why Hierarchical + Event-Driven (not one or the other)?

**Pure hierarchical without event bus:** Tier 1 would need to poll all operational systems. At scale (20+ simultaneous flights), polling latency makes the system too slow. Events eliminate polling.

**Pure event-driven without hierarchy:** Domain agents could make conflicting decisions without a global arbiter. Aviation cannot tolerate contradictory instructions to crew. The hierarchy provides conflict resolution.

**Together:** The event bus provides speed and decoupling. The hierarchy provides coherence and accountability.

### Why DAG at the Domain Level (not ReAct or Pipeline)?

**ReAct within a domain coordinator** would re-reason after every step. For a 5-step domain response plan with 3 parallel branches, ReAct would be sequential and 3–5x slower. DAG executes independent branches in parallel.

**Pipeline within a domain** would serialize independent actions. Notifying ramp crew and updating the load plan are independent — doing them in sequence wastes the overlap.

**DAG** builds the dependency graph once, runs parallel where possible, and only sequences where one output feeds the next input. It's the most time-efficient model for multi-step domain response.

### Why ReAct at Tier 1 (only for novel scenarios)?

Tier 1 handles two classes of events:
- **Recognized patterns** (80% of disruptions): handled by pre-built playbooks — Plan-Execute style, no LLM reasoning overhead
- **Novel compound disruptions** (20%): require actual reasoning about interdependencies — ReAct loop is invoked here only

This keeps Tier 1 fast for routine cases and capable for unusual ones.

---

## 9. Key Design Decisions and Their Rationale

| Decision | Choice | Why | What Was Rejected |
|---|---|---|---|
| Coordination model | Hierarchical | Aviation requires global coherence + audit trail | Swarm (no global state, poor debuggability) |
| Communication model | Event-driven bus | Millisecond reaction, full audit log, replay capability | Polling (too slow), direct agent-to-agent calls (tight coupling) |
| Within-domain execution | DAG (dependency graph) | Parallel execution of independent tasks; 3.6x speed | Pipeline (serial, too slow for transfer windows) |
| Tier 1 reasoning | Playbooks + ReAct for novel cases | Playbooks for speed, ReAct for edge cases | Pure ReAct everywhere (token cost, latency) |
| Autonomy level | Progressive (advisory → semi-auto → full auto) | Trust must be built; aviation has safety requirements | Full autonomy from day 1 (risk, regulatory) |
| Tier 3 agents | Stateless I/O wrappers | Decouples reasoning from system integrations | Fat execution agents with embedded logic (hard to swap) |

---

## 10. Failure Modes and Mitigations

| Failure | Impact | Mitigation |
|---|---|---|
| Tier 1 strategic supervisor crashes | No cross-domain conflict resolution | Hot standby replica; domain coordinators operate independently (degrade gracefully) |
| Event bus partition | Domain agents miss events | Event replay from persistent log; agents detect gaps via sequence numbers |
| Domain coordinator wrong decision | Bad action taken (e.g., wrong bag rerouted) | Every Tier 3 action writes to event log; human override possible within 30 seconds |
| Tier 3 system API down | Can't execute in one domain | Domain coordinator degrades gracefully; queues actions for retry; alerts human |
| Conflicting simultaneous activations | Two coordinators act on same resource | Distributed lock at resource level; Tier 1 arbitrates via conflict topic |

---

## 11. Why This Architecture Fits dCortex's Positioning

dCortex describes itself as: *"a coordinated system of intelligence, where multiple agents operate in tandem, continuously sensing, reasoning, and evolving with the environment — designed for environments where complexity is inherent, decisions are continuous, and outcomes cannot be predefined."*

This maps directly:
- **"Multiple agents in tandem"** → Hierarchical + event-driven coordination
- **"Continuously sensing"** → Event bus subscription model
- **"Reasoning"** → Tier 1 strategic supervisor + domain coordinator DAG planning
- **"Evolving with the environment"** → Episodic memory that improves playbooks from past disruptions
- **"Complexity is inherent, decisions are continuous"** → Exactly the IROPS baggage scenario

The architecture above is what dCortex likely builds, generalized across domains. For baggage, it is the first domain where the pattern is highly legible because the failure mode (transfer misconnection) is well-understood, the time window is quantifiable (minutes), and the cost of failure is measurable ($150/bag, $5B/year industry-wide).

---

## 12. Summary

The baggage coordination problem requires a system that is simultaneously:
- **Fast** (sub-2-minute response to transfer window events)
- **Coherent** (no conflicting instructions across domains)
- **Parallel** (multiple domain actions must fire simultaneously)
- **Adaptive** (disruptions evolve; the plan must evolve with them)
- **Auditable** (aviation requires full decision traceability)

No single agentic pattern satisfies all five. The **Event-Driven Hierarchical Supervisor with DAG domain execution** is the minimum viable architecture that satisfies all five constraints simultaneously, with each pattern applied at the tier where its strengths are most needed and its weaknesses are absorbed by adjacent tiers.

---

## Sources

- [Multi-Agent AI Orchestration Patterns — Lushbinary](https://lushbinary.com/blog/multi-agent-orchestration-patterns-supervisor-swarm-pipeline-router-guide/)
- [Agent Architectures: ReAct vs Plan-Execute vs Graph Agents — dasroot.net](https://dasroot.net/posts/2026/04/agent-architectures-react-plan-execute-graph-agents/)
- [Swarm vs. Supervisor: Multi-Agent Architecture Guide — Augment Code](https://www.augmentcode.com/guides/swarm-vs-supervisor)
- [AI Agent Orchestration Patterns 2026 — The Thinking Company](https://thinking.inc/en/blue-ocean/agentic/agent-orchestration-patterns/)
- [Choose a Design Pattern for Your Agentic AI System — Google Cloud](https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system)
- [Hierarchical Multi-Agent Systems — Over Coffee (Medium)](https://overcoffee.medium.com/hierarchical-multi-agent-systems-concepts-and-operational-considerations-e06fff0bea8c)
- [Event-Driven Multi-Agent Design — Sean Falconer (Medium)](https://seanfalconer.medium.com/ai-agents-must-act-not-wait-a-case-for-event-driven-multi-agent-design-d8007b50081f)
- [Multi-Agent System for Airline Operations Control — Academia.edu](https://www.academia.edu/187441/A_Multi_Agent_System_for_Airline_Operations_Control)
- [Designing a MAS for Airline Operations Recovery — Academia.edu](https://www.academia.edu/187448/Designing_a_Multi_Agent_System_for_Monitoring_and_Operations_Recovery_for_an_Airline_Operations_Control_Centre)
- [Disruption Management in Airline Operations — arXiv](https://arxiv.org/abs/2510.26831)
- [Agent Architecture Patterns Taxonomy 2026 — Digital Applied](https://www.digitalapplied.com/blog/agent-architecture-patterns-taxonomy-2026)
- [7 Agentic AI Design Patterns — DEV Community](https://dev.to/emperorakashi20/the-7-agentic-ai-design-patterns-every-developer-should-know-react-reflection-tool-use-and-more-3bba)
