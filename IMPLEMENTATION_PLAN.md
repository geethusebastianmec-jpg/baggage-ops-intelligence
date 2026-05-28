# Implementation Plan — Baggage Coordination Agentic Demo

**Role:** This document is the engineering contract. Every phase below has a
precise deliverable, acceptance criteria, and commit scope. Nothing is built
outside the phase it belongs to. Nothing from a later phase bleeds into an
earlier one.

**Demo target:** A 10-minute live scenario called **"The Hub Crisis"** —
3 simultaneous flight delays at JFK, 12 bags at risk of missing connections,
system autonomously saves 8, pre-notifies passengers on the 4 that cannot make
it, full audit trail visible in real-time dashboard. Zero human intervention
required.

---

## Project Layout (target end-state)

```
baggage/
├── IMPLEMENTATION_PLAN.md
├── README.md
├── Makefile                         ← make up / make demo / make down
├── docker-compose.yml               ← Redpanda, PostgreSQL, Redis
├── .env.example
├── requirements.txt
│
├── research/                        ← existing research docs
│
├── src/
│   ├── models/
│   │   ├── __init__.py
│   │   ├── flight.py                ← Flight, Gate, DelayEvent
│   │   ├── bag.py                   ← Bag, TransferConnection, BagStatus
│   │   └── events.py                ← DisruptionEvent, AgentDecision, ActionRecord
│   │
│   ├── tools/                       ← Tier 3: mock tool wrappers (no LLM)
│   │   ├── __init__.py
│   │   ├── bhs.py                   ← BHSTool (bag location, routing updates)
│   │   ├── load_plan.py             ← LoadPlanTool (aircraft W&B docs)
│   │   ├── ramp.py                  ← RampTool (crew tasks, equipment)
│   │   ├── passenger_notify.py      ← PassengerNotifyTool (SMS/push mock)
│   │   └── aodb.py                  ← AODBTool (flight status, gate data)
│   │
│   ├── tier2/                       ← Domain coordinators (LangGraph DAGs)
│   │   ├── __init__.py
│   │   ├── state.py                 ← Shared TypedDict state schemas
│   │   ├── baggage_coordinator.py
│   │   ├── ramp_coordinator.py
│   │   ├── dispatch_coordinator.py
│   │   └── comms_coordinator.py
│   │
│   ├── tier1/                       ← Strategic supervisor
│   │   ├── __init__.py
│   │   ├── playbooks.py             ← Known disruption patterns + responses
│   │   └── supervisor.py            ← LangGraph supervisor + ReAct fallback
│   │
│   ├── events/                      ← Kafka producers and consumers
│   │   ├── __init__.py
│   │   ├── topics.py                ← Topic name constants
│   │   ├── producer.py              ← Generic event producer
│   │   └── consumer.py              ← Per-domain consumer base class
│   │
│   ├── memory/                      ← State and memory clients
│   │   ├── __init__.py
│   │   ├── redis_client.py          ← Operational working memory
│   │   └── checkpointer.py          ← LangGraph PostgreSQL checkpointer
│   │
│   └── api/                         ← FastAPI service
│       ├── __init__.py
│       ├── main.py                  ← App entrypoint, WebSocket broadcast
│       └── routers/
│           ├── status.py            ← GET /status/{disruption_id}
│           └── override.py          ← POST /override (HITL)
│
├── demo/
│   ├── seed_data.py                 ← Hub airport, flights, bags, connections
│   ├── scenario_runner.py           ← Injects delay events, orchestrates demo
│   └── dashboard.py                 ← Streamlit real-time UI
│
└── tests/
    ├── test_models.py
    ├── test_tools.py
    ├── test_tier2_baggage.py
    ├── test_tier2_ramp.py
    ├── test_tier1_supervisor.py
    └── test_scenario.py             ← End-to-end smoke test
```

---

## Phase 0 — Research Foundation ✅ COMPLETE

**Already committed.** Three documents covering:
- Current state of airline baggage operations ($5B/year problem)
- Chosen architecture: Event-Driven Hierarchical Supervisor + DAG domain execution
- Full tech stack selection with tradeoff rationale

---

## Phase 1 — Repo Scaffold + Infrastructure

**What it delivers:** A runnable local dev environment. One command brings up
all services. Nothing agentic yet — just the foundation everything else sits on.

**Files created:**
- `docker-compose.yml` — Redpanda (Kafka-compatible), PostgreSQL 16, Redis 7
- `requirements.txt` — all Python dependencies pinned
- `.env.example` — all required env vars documented
- `Makefile` — `make up`, `make down`, `make logs`, `make demo`, `make test`
- `README.md` — how to run the project from zero

**Infrastructure services:**

| Service | Image | Port | Purpose |
|---|---|---|---|
| Redpanda | `redpandadata/redpanda:latest` | 9092, 9644 | Kafka-compatible event bus (single binary, no Zookeeper) |
| PostgreSQL | `postgres:16-alpine` | 5432 | LangGraph checkpoint store + domain rules |
| Redis | `redis:7-alpine` | 6379 | Working memory, distributed locks |

**Why Redpanda over Kafka for demo:**
Kafka requires Zookeeper + a broker + schema registry = 3 containers minimum.
Redpanda is a single container with the same Kafka API, Kafka-compatible
producer/consumer libraries work unchanged, and it starts in 2 seconds.
All code written against `confluent-kafka` Python client runs identically against
both. Swap to real Kafka for production by changing one URL in `.env`.

**Key dependencies:**
```
langgraph==0.2.*
langgraph-supervisor==0.0.*
langgraph-checkpoint-postgres==2.*
langchain-anthropic==0.3.*
confluent-kafka==2.*
redis==5.*
psycopg2-binary==2.*
qdrant-client==1.*
fastapi==0.115.*
uvicorn==0.30.*
websockets==13.*
streamlit==1.40.*
pydantic==2.*
python-dotenv==1.*
rich==13.*
pytest==8.*
pytest-asyncio==0.*
```

**Acceptance criteria:**
- `make up` → all 3 services healthy, no port conflicts
- `make down` → clean teardown, no dangling volumes
- `python -c "import langgraph, confluent_kafka, redis, fastapi"` exits 0
- `.env.example` documents every required key with a description

**Commit message:** `feat(infra): docker compose scaffold + dependencies`

---

## Phase 2 — Domain Data Models

**What it delivers:** The shared language of the entire system. Every agent,
tool, and event uses these types. No agent logic yet — just types.

**Core models:**

```python
# models/flight.py
class Flight(BaseModel):
    flight_id: str          # e.g. "AA123"
    origin: str             # IATA code
    destination: str        # IATA code
    scheduled_departure: datetime
    estimated_departure: datetime
    gate: str
    status: FlightStatus    # ON_TIME | DELAYED | CANCELLED | DEPARTED

class DelayEvent(BaseModel):
    flight_id: str
    delay_minutes: int
    reason: DelayReason     # WEATHER | CREW | MECHANICAL | ATC | CONNECTING
    detected_at: datetime
    source: str             # "ACARS" | "ATC" | "MANUAL"

# models/bag.py
class Bag(BaseModel):
    bag_tag: str            # 10-digit IATA tag
    passenger_id: str
    origin_flight: str
    destination_flight: str  # None if final destination
    status: BagStatus       # CHECKED_IN | IN_TRANSIT | LOADED | DELIVERED | EXCEPTION
    current_location: str   # BHS zone or aircraft hold

class TransferConnection(BaseModel):
    bag_tag: str
    inbound_flight: str
    outbound_flight: str
    connection_window_minutes: int
    minimum_connection_time: int    # airport-specific minimum
    is_at_risk: bool
    risk_reason: str | None

# models/events.py
class DisruptionEvent(BaseModel):
    event_id: str
    event_type: DisruptionType  # FLIGHT_DELAY | GATE_CHANGE | CANCELLATION | EQUIPMENT_FAILURE
    payload: dict
    severity: Severity          # LOW | MEDIUM | HIGH | CRITICAL
    affected_flights: list[str]
    created_at: datetime

class AgentDecision(BaseModel):
    decision_id: str
    agent: str              # "tier1_supervisor" | "baggage_coordinator" etc
    disruption_id: str
    reasoning: str
    action: str
    confidence: float
    created_at: datetime

class ActionRecord(BaseModel):
    action_id: str
    decision_id: str
    tool: str               # "bhs" | "load_plan" | "ramp" | "passenger_notify"
    input: dict
    output: dict
    success: bool
    executed_at: datetime
    duration_ms: int
```

**Acceptance criteria:**
- All models import cleanly
- All models serialize/deserialize from JSON without loss
- `pytest tests/test_models.py` passes

**Commit message:** `feat(models): domain data models for flights, bags, events`

---

## Phase 3 — Tier 3: Mock Tool Layer

**What it delivers:** Realistic mock implementations of every airline operational
API. These are the only things that touch "external systems." All are deterministic
given seed data, but support configurable failure injection for demo resilience testing.

**Design principle:** Each tool is a plain Python class with a `run(input) → output`
method. LangGraph wraps them as tool nodes. No LLM involved at this layer —
all logic is deterministic.

**Tools:**

```python
# tools/bhs.py — Baggage Handling System
class BHSTool:
    def query_bag(self, bag_tag: str) -> Bag
    def query_transfer_risks(self, inbound_flight: str) -> list[TransferConnection]
    def update_bag_routing(self, bag_tag: str, new_route: str) -> bool
    def open_exception_routing(self, bag_tags: list[str], reason: str) -> ExceptionTicket

# tools/load_plan.py — Aircraft weight & balance
class LoadPlanTool:
    def get_load_plan(self, flight_id: str) -> LoadPlan
    def update_bag_count(self, flight_id: str, delta: int) -> LoadPlan
    def flag_pending_bags(self, flight_id: str, bag_tags: list[str]) -> bool

# tools/ramp.py — Ground crew & equipment
class RampTool:
    def get_crew_availability(self, zone: str) -> CrewStatus
    def assign_exception_task(self, bag_tags: list[str], from_flight: str, to_flight: str) -> TaskTicket
    def get_equipment_status(self, equipment_id: str) -> EquipmentStatus

# tools/passenger_notify.py — Passenger communications
class PassengerNotifyTool:
    def notify_bag_at_risk(self, passenger_id: str, bag_tag: str, message: str) -> bool
    def notify_bag_missed(self, passenger_id: str, bag_tag: str, delivery_eta: str) -> bool
    def notify_bag_recovered(self, passenger_id: str, bag_tag: str) -> bool

# tools/aodb.py — Airport Operations Database
class AODBTool:
    def get_flight_status(self, flight_id: str) -> Flight
    def get_gate_info(self, gate_id: str) -> GateInfo
    def get_departure_window(self, flight_id: str) -> int   # minutes until hard out
```

**Mock data behavior:**
- Tools read from in-memory seed data (loaded from `demo/seed_data.py`)
- Configurable artificial latency (default 50–200ms to simulate real API calls)
- Configurable failure rate for testing error handling
- All actions logged to an in-memory audit list that the dashboard reads

**Acceptance criteria:**
- Each tool callable independently with no external services running
- `pytest tests/test_tools.py` passes — covers query, update, and failure paths
- Tool calls print structured logs with input/output for demo visibility

**Commit message:** `feat(tools): tier3 mock tool layer — BHS, load plan, ramp, comms, AODB`

---

## Phase 4 — Tier 2: Baggage Domain Coordinator

**What it delivers:** The first real LangGraph agent. Handles transfer risk
events. This is where the architecture becomes demonstrable — parallel DAG
execution across multiple tool calls, driven by an LLM that reasons about
feasibility and routes correctly.

**State schema:**
```python
class BaggageCoordinatorState(TypedDict):
    disruption_id: str
    triggering_event: DisruptionEvent
    at_risk_bags: list[TransferConnection]
    bhs_query_result: list[Bag]
    departure_window: int           # minutes until outbound departs
    ramp_capacity: CrewStatus
    feasibility_verdict: str        # "RECOVERABLE" | "PARTIAL" | "UNRECOVERABLE"
    actions_taken: list[ActionRecord]
    messages: Annotated[list, add_messages]
```

**DAG graph structure:**
```
START
  │
  ├──[query_bhs_node]          ← parallel fan-out
  ├──[check_departure_node]    ← parallel fan-out
  └──[get_ramp_capacity_node]  ← parallel fan-out
          │
    [evaluate_feasibility_node]   ← converge, LLM reasoning here
          │
     ┌────┴─────┐
     │          │
[route_bags]  [flag_missed]    ← conditional branch
     │          │
[notify_ops] [notify_passengers]
     │          │
    END        END
```

**Key implementation detail:**
The only LLM call in this entire graph is `evaluate_feasibility_node`. It
receives: `at_risk_bags`, `departure_window`, `ramp_capacity`, and the BHS
query result — and outputs a structured `feasibility_verdict` with reasoning.
Everything before and after is deterministic tool execution.

**Model:** Claude Sonnet 4.5 (`claude-sonnet-4-5`)

**Acceptance criteria:**
- Given seed data: 3 bags at risk on a 20-min delayed inbound, 15-min departure window on outbound:
  - Coordinator correctly identifies 2 as recoverable, 1 as missed
  - Exception routing opened for 2 recoverable bags
  - Passenger notified for the 1 missed bag
  - Total wall-clock time < 8 seconds
- `pytest tests/test_tier2_baggage.py` passes with mocked LLM responses

**Commit message:** `feat(tier2): baggage domain coordinator — parallel DAG with feasibility reasoning`

---

## Phase 5 — Tier 2: Ramp, Dispatch, Comms Coordinators

**What it delivers:** The remaining three domain coordinators. Each follows the
same DAG pattern as the Baggage Coordinator but owns a different operational domain.

**Ramp Coordinator:**
- Triggered by: BaggageExceptionEvent (bags need physical rerouting)
- DAG: [get zone crew] + [get equipment] → [assign exception task] → [confirm task]
- Owns: crew allocation, tug routing, hold reopening decisions
- LLM call: deciding whether to assign existing crew or request additional resources

**Dispatch Coordinator:**
- Triggered by: DepartureHoldRequestEvent
- DAG: [get departure constraints] + [get load plan status] + [get crew ready status] → [hold/release decision]
- Owns: departure hold approvals, load plan sign-off, network impact assessment
- LLM call: hold vs. depart decision when trade-off is non-trivial (e.g., 3 bags vs. 15-min delay cost)
- This coordinator is the one most likely to trigger a cross-domain conflict with the Baggage Coordinator → resolved by Tier 1

**Comms Coordinator:**
- Triggered by: any BagStatusChangeEvent
- DAG: [get passenger PNR] + [get bag status] → [compose message] → [send notification]
- Owns: all outbound passenger and operational communications
- LLM call: composing context-appropriate message (recovery ETA vs. apology vs. delivery info)
- No conflicts possible — Comms is read-only and notification-only

**Acceptance criteria:**
- Each coordinator handles its trigger event end-to-end
- RampCoordinator assigns correct crew given seed ramp data
- DispatchCoordinator correctly decides to hold when 3+ bags are recoverable within 5 min
- CommsCoordinator sends correctly templated messages per scenario
- `pytest tests/test_tier2_ramp.py` passes

**Commit message:** `feat(tier2): ramp, dispatch, comms domain coordinators`

---

## Phase 6 — Tier 1: Strategic Supervisor

**What it delivers:** The global brain. Receives all disruption events, classifies
them, activates the correct domain coordinators in parallel, and arbitrates
cross-domain conflicts.

**Two modes of operation:**

**Playbook mode (80% of events):**
Pre-defined response patterns. No LLM reasoning — just pattern match + activate.
Fast, predictable, zero-cost.

```python
PLAYBOOKS = {
    DisruptionType.FLIGHT_DELAY: PlayBook(
        activate=["baggage_coordinator", "ramp_coordinator"],
        condition=lambda e: e.payload["delay_minutes"] >= 10,
        priority=Priority.HIGH
    ),
    DisruptionType.GATE_CHANGE: PlayBook(
        activate=["ramp_coordinator", "comms_coordinator"],
        condition=lambda e: True,
        priority=Priority.MEDIUM
    ),
    DisruptionType.CANCELLATION: PlayBook(
        activate=["baggage_coordinator", "dispatch_coordinator", "comms_coordinator"],
        condition=lambda e: True,
        priority=Priority.CRITICAL
    ),
}
```

**ReAct mode (20% of events — novel/compound disruptions):**
LangGraph ReAct agent using Claude Opus 4 (`claude-opus-4-0`). Given multiple
simultaneous disruption events, reasons about their interdependencies and
builds a custom activation plan. More token-expensive, only invoked when no
playbook matches or when a compound disruption is detected.

**Conflict resolution:**
When two domain coordinators publish conflicting decisions to `ops.decisions.conflicts`:
1. Supervisor reads both decisions and their reasoning
2. LLM (Claude Opus) arbitrates using cost model: delay cost vs. mishandled bag cost vs. network cascade cost
3. Winning decision is published to `ops.decisions.resolved`
4. Losing coordinator's in-flight action is cancelled via interrupt

**Acceptance criteria:**
- Single delay event → correct playbook fires, correct coordinators activated in parallel, <500ms from event to activation
- Compound event (delay + gate change on same flight) → ReAct mode invoked, correct combined response
- Conflict scenario (Ramp wants to hold, Dispatch wants to depart) → Tier 1 correctly arbitrates based on bag count
- `pytest tests/test_tier1_supervisor.py` passes

**Commit message:** `feat(tier1): strategic supervisor — playbooks, react fallback, conflict resolution`

---

## Phase 7 — Kafka Event Bus Wiring

**What it delivers:** The nervous system. Connects everything built so far into
a live reactive system. Events flow from producers (simulated airline systems)
through Redpanda to the correct domain coordinator consumers.

**Producer side:**
```python
# events/producer.py
class EventProducer:
    def publish_delay(self, event: DelayEvent) -> None
    def publish_gate_change(self, event: GateChangeEvent) -> None
    def publish_action(self, record: ActionRecord) -> None  # audit log
```

**Consumer side:**
Each domain coordinator runs as an async consumer. The consumer loop:
1. Poll Kafka for new events on subscribed topics
2. Deserialize to the appropriate Pydantic model
3. Invoke the coordinator's LangGraph graph with the event as input
4. Write all resulting ActionRecords to `ops.audit.actions` topic

```python
# events/consumer.py
class DomainConsumer:
    topics: list[str]
    coordinator_graph: CompiledStateGraph

    async def run(self):
        while True:
            msg = self.consumer.poll(timeout=0.1)
            if msg:
                event = DisruptionEvent.model_validate_json(msg.value())
                await self.coordinator_graph.ainvoke({"triggering_event": event})
```

**Topic → coordinator mapping:**

| Topic | Consumed By |
|---|---|
| `ops.flights.delays` | Baggage Coordinator, Ramp Coordinator |
| `ops.flights.gate-changes` | Ramp Coordinator, Comms Coordinator |
| `ops.flights.cancellations` | All coordinators |
| `ops.baggage.exceptions` | Dispatch Coordinator, Comms Coordinator |
| `ops.ramp.crew-status` | Baggage Coordinator |
| `ops.decisions.conflicts` | Tier 1 Supervisor (conflict resolver) |
| `ops.audit.actions` | Dashboard, audit log |

**Acceptance criteria:**
- Publish a single delay event → all subscribed coordinators receive it within 200ms
- Coordinator processes event → ActionRecords appear on `ops.audit.actions` topic
- Coordinator crash + restart → resumes from LangGraph checkpoint, no duplicate actions
- `make logs` shows structured event flow across all consumers

**Commit message:** `feat(events): kafka producers and consumers — full event bus wiring`

---

## Phase 8 — Demo Seed Data + Scenario Runner

**What it delivers:** The specific dataset and script that drives the demo.
Running `python demo/scenario_runner.py` produces the full "Hub Crisis" scenario.

**Seed data (`demo/seed_data.py`):**

JFK Hub — 5 flights loaded into mock tools:

| Flight | Status | Delay |
|---|---|---|
| AA401 (ORD→JFK) | DELAYED | +32 min |
| AA402 (LAX→JFK) | DELAYED | +18 min |
| AA403 (MIA→JFK) | DELAYED | +11 min |
| AA501 (JFK→LHR) | ON_TIME | departs in 25 min |
| AA502 (JFK→CDG) | ON_TIME | departs in 40 min |

40 bags total, 12 with active connections:
- 7 bags from AA401 → AA501 (32-min delay, 25-min window → window breached by 7 min)
- 3 bags from AA402 → AA501 (18-min delay, 25-min window → tight but potentially recoverable)
- 2 bags from AA403 → AA502 (11-min delay, 40-min window → comfortable)

**Expected resolution:**
- 7 bags AA401→AA501: 5 recoverable via exception routing + ramp sprint, 2 truly missed
- 3 bags AA402→AA501: all 3 recoverable (within window)
- 2 bags AA403→AA502: no action needed (not at risk)
- **Total: 8 saved, 2 missed, 2 flagged no-action-needed**

**Scenario runner steps:**
1. Load seed data into mock tools and Redis
2. Wait 2 seconds (simulate normal operation)
3. Inject `DelayEvent(AA401, +32min)` → Kafka
4. Inject `DelayEvent(AA402, +18min)` → Kafka (500ms later, simultaneous IROPS)
5. Inject `DelayEvent(AA403, +11min)` → Kafka (1s later)
6. Wait for all coordinators to complete
7. Print outcome summary: bags saved, bags missed, actions taken, time elapsed

**Acceptance criteria:**
- `python demo/scenario_runner.py` runs end-to-end without error
- Outcome matches expected: 8 saved, 2 missed, 2 no-action
- Total wall-clock time < 30 seconds
- All actions written to audit topic
- `pytest tests/test_scenario.py` passes (deterministic with mocked LLM)

**Commit message:** `feat(demo): seed data and scenario runner — hub crisis scenario`

---

## Phase 9 — Demo Dashboard

**What it delivers:** The visual layer that makes the demo legible to a non-technical
audience. A live Streamlit dashboard that shows what the system is doing in real-time.

**Dashboard layout:**

```
┌─────────────────────────────────────────────────────────────────────┐
│  BAGGAGE OPS INTELLIGENCE               JFK Hub — Live              │
├────────────────────┬──────────────────┬─────────────────────────────┤
│  FLIGHT STATUS     │  AGENT ACTIVITY  │  BAG BOARD                  │
│                    │                  │                             │
│  AA401  DELAYED    │  [Tier 1]        │  ● 8 SAVED                  │
│         +32 min    │  Playbook match  │  ● 2 MISSED                 │
│                    │  → Baggage+Ramp  │  ● 2 NO ACTION              │
│  AA402  DELAYED    │                  │                             │
│         +18 min    │  [Baggage Coord] │  AT-RISK BAGS               │
│                    │  DAG executing   │  BA-001 → AA501  ✓ SAVED    │
│  AA403  DELAYED    │  Evaluating...   │  BA-002 → AA501  ✓ SAVED    │
│         +11 min    │                  │  BA-003 → AA501  ✗ MISSED   │
│                    │  [Ramp Coord]    │  ...                        │
│  AA501  ON TIME    │  Crew assigned   │                             │
│  AA502  ON TIME    │  Task: Zone B    │                             │
├────────────────────┴──────────────────┴─────────────────────────────┤
│  DECISION TIMELINE                                                  │
│  12:00:01  [Tier 1] AA401 delay detected → Baggage + Ramp activated │
│  12:00:03  [Baggage] 7 bags at risk identified on AA401→AA501       │
│  12:00:04  [Baggage] 5 recoverable, 2 missed — exception routing    │
│  12:00:05  [Ramp] Crew assigned to Zone B, ETA 4 min               │
│  12:00:06  [Comms] Passengers BA-003, BA-007 notified (missed)      │
├─────────────────────────────────────────────────────────────────────┤
│  HUMAN OVERRIDE                                                     │
│  [Override Decision]  [Pause System]  [Replay from Checkpoint]      │
└─────────────────────────────────────────────────────────────────────┘
```

**Implementation:**
- FastAPI WebSocket endpoint (`/ws/events`) streams Kafka audit events as JSON
- Streamlit dashboard connects to WebSocket, updates state on each event
- Streamlit `st.rerun()` or `st.empty()` containers for live updates
- Override button POSTs to FastAPI `/override` which injects a decision into Tier 1

**Acceptance criteria:**
- Dashboard launches with `streamlit run demo/dashboard.py`
- When `scenario_runner.py` runs, dashboard updates in real-time within 1 second of each agent action
- Bag board shows correct final counts after scenario completes
- Override button visible and functional (submits to FastAPI, logged in decision timeline)

**Commit message:** `feat(demo): streamlit dashboard — real-time agent activity and bag board`

---

## Phase Summary

| Phase | Deliverable | New Files | Key Tech |
|---|---|---|---|
| 0 | Research docs ✅ | research/ | — |
| 1 | Infra scaffold | docker-compose.yml, requirements.txt, Makefile | Redpanda, Postgres, Redis |
| 2 | Data models | src/models/ | Pydantic v2 |
| 3 | Tool layer | src/tools/ | Plain Python, no LLM |
| 4 | Baggage Coordinator | src/tier2/baggage_coordinator.py | LangGraph DAG, Claude Sonnet |
| 5 | Remaining coordinators | src/tier2/{ramp,dispatch,comms}_coordinator.py | LangGraph DAG, Claude Sonnet |
| 6 | Strategic supervisor | src/tier1/ | LangGraph Supervisor, Claude Opus |
| 7 | Event bus wiring | src/events/ | confluent-kafka, Redpanda |
| 8 | Demo scenario | demo/seed_data.py, scenario_runner.py | Rich CLI output |
| 9 | Dashboard | demo/dashboard.py, src/api/ | Streamlit, FastAPI, WebSocket |

---

## Rules of Engagement

1. **Each phase ships as one commit.** No partial phase commits unless the phase
   explicitly subdivides itself (only Phase 5 does, with 3 coordinators).

2. **No phase starts before the previous one's acceptance criteria pass.**
   Each phase's test file is written before the implementation (test-first within
   each phase, not across phases).

3. **No LLM calls in Tier 3.** Ever. Tool nodes are deterministic.

4. **State schemas are immutable within a phase.** If a later phase needs a new
   field, it adds it without breaking existing fields.

5. **The demo scenario is the integration test.** If `python demo/scenario_runner.py`
   produces wrong outcomes, the relevant phase is re-opened, not worked around.

6. **Every commit passes `make test`.** No green-on-main exceptions.

---

## Environment Variables Required

```bash
# LLM
ANTHROPIC_API_KEY=sk-ant-...

# Kafka (Redpanda)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# PostgreSQL (checkpointer)
POSTGRES_DSN=postgresql://baggage:baggage@localhost:5432/baggage_ops

# Redis (working memory)
REDIS_URL=redis://localhost:6379/0

# LangSmith (observability — optional for demo, recommended)
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=baggage-demo

# Demo config
DEMO_AIRPORT=JFK
LLM_TIER1_NOVEL=claude-opus-4-0
LLM_TIER1_PLAYBOOK=claude-sonnet-4-5
LLM_TIER2=claude-sonnet-4-5
```
