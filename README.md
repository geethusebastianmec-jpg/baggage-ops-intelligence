# Baggage Ops Intelligence

> Autonomous multi-agent AI that coordinates airline baggage operations in real time —
> detecting transfer connection failures before they happen and acting across baggage,
> ramp, and dispatch domains simultaneously.

Built by **dCortex** as a demonstration of operational superintelligence applied to the airline industry.

---

## The Problem

Airlines mishandle **33 million bags per year** at a cost of **$5 billion**. The biggest
single cause — **41% of all failures** — is transfer misconnections: a flight arrives late,
and no one coordinates fast enough to get the connecting bags onto the outbound flight before
it closes. Today, a human coordinator in the AOCC (Airline Operations Control Centre) does this
manually: one phone call to baggage, one to ramp crew, one to dispatch, one to passenger services.
By the time all four are done, the window is gone.

> **New to the domain?** Read the [plain-English explainer](research/explainer-for-beginners.md)
> first — it walks through what happens to a bag, why connections are missed, and exactly how
> this system fixes it.

---

## The Solution

Replace those four sequential phone calls with one automated system that makes all four
decisions **simultaneously**, in under 2 seconds, using the right tool for each question.

```
Flight delay detected
    ↓
Strategic Supervisor  (playbook match  →  Gemini Pro for novel events only)
    ↓  activates in parallel
    ├─ Baggage Coordinator
    │    BHS query → deterministic triage (slack math) → CP-SAT if crew contended
    │    → exception routing + ramp crew assignment + passenger notifications
    ├─ Ramp Coordinator
    │    crew availability → assign exception transfer task
    └─ Dispatch Coordinator
         cost comparison ($150/bag vs $500/min) → hold or depart
    ↓
ActionRecords  →  Kafka  →  audit trail + live dashboard
```

### The design principle: use the simplest correct tool

Every question in the system is answered at the cheapest tier that gets it right:

| Tier | Tool | Question answered |
|---|---|---|
| 0 | State store | Where is bag X right now? |
| 1 | Deterministic rules | Is this bag at risk? (`slack = window − move_time`) · Who gets notified? · Hold or depart? |
| 2 | **CP-SAT solver** | Multiple bags competing for scarce crew — which subset do we save? |
| 3 | Thin agent loop | Which of the above does this situation need, and in what order? |
| 4 | LLM (last resort) | Novel compound disruptions no playbook covers |

The LLM is not in the feasibility calculation. Feasibility is arithmetic.
The LLM decides which coordinators to activate for situations it has never seen before.

---

## Demo Scenario — The Hub Crisis

JFK hub. Three inbound flights delayed simultaneously. 12 bags at risk.

| Flight | Route | Delay | Connecting bags | Outbound |
|--------|-------|-------|-----------------|---------|
| AA401 | ORD → JFK | **+32 min** | 7 bags | AA501 (JFK → LHR, departs in 25 min) |
| AA402 | LAX → JFK | **+18 min** | 3 bags | AA501 (JFK → LHR, departs in 25 min) |
| AA403 | MIA → JFK | **+11 min** | 2 bags | AA502 (JFK → CDG, departs in 40 min) |

The physical bag move time at JFK ranges from 8 minutes (BHS Zone B, near the gate)
to 22 minutes (Zone D, far queue). This — not an LLM judgment — is what determines
which bags can make it.

| Bag | BHS zone | Move time | Slack (25 min window) | Outcome |
|---|---|---|---|---|
| BA-001 → BA-005 | Zone B | 8 min | **+17 min** | RUSH — exception routing ✅ |
| BA-006, BA-007 | Zone D | 26 min | **-1 min** | Physically impossible ❌ |
| BA-008 → BA-010 (AA402) | Zone B | 8 min | **+7 min** | RUSH ✅ |
| BA-011, BA-012 (AA403) | Zone C | 10 min | **+30 min** | No action needed ✅ |

**Outcome:** 8 bags saved, 2 missed, 2 no-action. All affected passengers notified
automatically — no human needed.

---

## What's Handled

| Scenario | Status | Notes |
|---|---|---|
| **Flight delay → transfer misconnection** | ✅ Full | Slack triage (Tier 1) + CP-SAT for contention (Tier 2) + confirming scan feedback loop. Full AT_RISK → RECOVERED / MISSED notification lifecycle. Covers 41% of all mishandling. |
| **Gate change** | ✅ Full | `gate_change_coordinator`: finds bags sorted to old gate, BHS divert command, crew reassignment, load plan update, passenger notification. |
| **Loading failure at origin** | ✅ Full | `loading_failure_coordinator`: locate bag → check flight at gate → emergency load if time permits, else rebook on next flight + MISSED notification. Covers 16% of mishandling. |
| **BHS equipment failure** | ✅ Full | `equipment_coordinator`: identify impacted bags in failed zone, reroute to alternate BHS path, alert maintenance, re-run triage for newly at-risk bags. |
| **Network cascade** | ✅ Full | `network_cascade_coordinator`: aggregates all at-risk bags across multiple simultaneous delayed inbounds, runs single joint CP-SAT under true shared crew constraint. Prevents N separate coordinators overpromising on the same crew. |
| **Flight cancellation** | 🟡 Partial | All bags correctly flagged unrecoverable. Passenger notified. Rebooking on alternate flights and physical off-load of loaded bags not yet implemented. |
| **ATC / SLOT delay** | 🟡 Partial | Treated as a standard flight delay. Full delay pipeline runs. SLOT-specific ground stop windows not separately modelled. |
| **Mechanical delay** | 🟡 Partial | Treated as a flight delay. Works for delays with known duration. Open-ended "unknown duration" mechanical holds not handled. |
| **Compound / novel event** | 🟡 Partial | Gemini Pro selects which coordinators to activate. NETWORK_CASCADE playbook handles the most common compound case (multiple delayed inbounds). Truly novel situations use LLM routing. |
| **Security hold on a bag** | ❌ Not yet | `ExceptionType.SECURITY_HOLD` exists in models. No coordinator, no event flow. |
| **Ramp crew shortage** | ❌ Not yet | RampCoordinator escalates when no crew is available. No adjacent-zone crew pull or proactive crew sourcing. |

### Passenger notification lifecycle

Every impacted passenger is notified automatically at each stage — no human needed:

| Status | Notification | When |
|---|---|---|
| Exception routing opened | `AT_RISK` | Immediately when ramp crew is dispatched to rush the bag |
| Confirming scan received | `RECOVERED` | When BHS scan confirms bag physically loaded on outbound aircraft |
| Window too short / crew unavailable | `MISSED` | Immediately when triage determines bag cannot make it |
| Loading failure — emergency loaded | `RECOVERED` | After emergency ramp sprint succeeds |
| Loading failure — rebooking | `MISSED` + delivery ETA | Bag booked on next available flight |

---

## Architecture

**Event-Driven Hierarchical Supervisor** with per-domain **LangGraph DAGs**.
Each coordinator uses the correct decision tier internally — no LLM in the feasibility path.

```
┌──────────────────────────────────────────────────────────────────┐
│  Strategic Supervisor (Tier 3 + Tier 4)                          │
│  Playbook registry — 7 known disruption types, no LLM            │
│  Gemini 1.5 Pro — novel/compound events only (Tier 4)            │
│  Cross-domain conflict arbitration                               │
└────────────────────┬─────────────────────────────────────────────┘
                     │  events via Kafka
   ┌─────────────────┼────────────┬───────────────┬──────────────┐
   ▼                 ▼            ▼               ▼              ▼
Baggage          Gate Change  Loading         Equipment    Network
Coordinator      Coordinator  Failure         Coordinator  Cascade
(delay→triage    (divert      Coordinator     (reroute     Coordinator
 →CP-SAT→        +crew        (emergency      +maintenance (joint CP-SAT
 dispatch)       reassign)    load|rebook)    alert)        all inbounds)
   │
   ├─ Tier 1: slack triage per bag (window − move_time)
   ├─ Tier 1: contention check
   ├─ Tier 2: CP-SAT if contended (OR-Tools)
   └─ close_loop: confirming scan → RECOVERED notification
   │
   ▼
Tool Layer (Tier 0 — no LLM)
BHS · AODB · Load Plan · Ramp · Passenger Notify
```

---

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| Agent framework | **LangGraph** | DAG execution, hierarchical supervisor, checkpointing |
| Feasibility solver | **OR-Tools CP-SAT** | Optimal bag recovery under crew contention — Tier 2 |
| LLM | **Gemini 1.5 Pro** | Novel compound disruptions only — Tier 4, Strategic Supervisor |
| Event bus | **Redpanda** (Kafka-compatible) | Durable audit log, fan-out, event replay |
| Backend API | **FastAPI** + WebSocket | Scenario triggers, live event streaming |
| Frontend | **Streamlit** | Real-time agent activity dashboard |
| Checkpoint store | **PostgreSQL** | LangGraph state persistence, fault recovery |
| Working memory | **Redis** | Shared agent state, sub-ms reads |

---

## Running the App

### Option 1 — CLI demo (fastest, no Docker needed)

```bash
git clone https://github.com/YOUR_USERNAME/baggage.git
cd baggage

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux

pip install -r requirements.txt

cp .env.example .env
# Add your GOOGLE_API_KEY to .env for real LLM calls (Strategic Supervisor only).
# Leave blank to run with mocked LLM — all deterministic logic still runs.

python demo/scenario_runner.py
```

---

### Option 2 — Streamlit dashboard (visual, no Docker)

```bash
# Terminal 1 — API backend
uvicorn src.api.main:app --port 8000

# Terminal 2 — dashboard
python -m streamlit run demo/dashboard.py
```

Open **http://localhost:8501** and click **"Run Hub Crisis Scenario"**.

---

### Option 3 — Full stack with Kafka + Postgres + Redis (Docker required)

```bash
# Start infrastructure
docker compose up -d

# Create Kafka topics (after ~15 seconds)
docker exec baggage_redpanda rpk topic create \
  ops.flights.delays ops.flights.gate-changes ops.flights.cancellations \
  ops.baggage.exceptions ops.ramp.crew-status ops.equipment.alerts \
  ops.decisions.conflicts ops.decisions.resolved ops.decisions.playbooks \
  ops.audit.actions --partitions 4 --replicas 1

# Terminal 1 — API
uvicorn src.api.main:app --port 8000

# Terminal 2 — Kafka worker (runs the agents)
python src/worker.py

# Terminal 3 — dashboard
python -m streamlit run demo/dashboard.py
```

Redpanda Console: **http://localhost:8080** — watch messages flowing through topics live.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | For real LLM calls | Google AI Studio key — [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Used only by the Strategic Supervisor for novel events. |
| `KAFKA_BOOTSTRAP_SERVERS` | Option 3 | `localhost:19092` local or Redpanda Cloud URL |
| `POSTGRES_DSN` | Option 3 | PostgreSQL connection string |
| `REDIS_URL` | Option 3 | Redis connection URL |
| `API_URL` | Options 2 + 3 | FastAPI backend URL (default: `http://localhost:8000`) |
| `LLM_TIER1_NOVEL` | No | Gemini model for novel disruptions (default: `gemini-1.5-pro`) |

---

## Deploying

Full guide in [`DEPLOY.md`](DEPLOY.md). Uses **Railway** (app services) +
**Redpanda Cloud** (managed Kafka, free tier) + **Railway Postgres + Redis**.

---

## Project Structure

```
baggage/
├── src/
│   ├── config.py                   All settings (reads from .env)
│   ├── worker.py                   Kafka consumer service entry point
│   ├── models/                     Pydantic types — Flight, Bag, DisruptionEvent, etc.
│   ├── tools/                      Tier 0: BHS, load plan, ramp, AODB mock wrappers
│   ├── solver/                     Tier 1 + 2: triage math + CP-SAT optimizer
│   │   ├── triage.py               Deterministic slack-based bag triage
│   │   └── optimizer.py            OR-Tools CP-SAT for contended recovery
│   ├── tier2/                      Domain coordinators (LangGraph DAGs)
│   │   ├── baggage_coordinator.py       Delay: triage → CP-SAT → dispatch → close_loop
│   │   ├── gate_change_coordinator.py   Gate change: divert bags + reassign crew
│   │   ├── loading_failure_coordinator.py  Not loaded: emergency load or rebook
│   │   ├── equipment_coordinator.py     Belt/scanner failure: reroute + alert
│   │   ├── network_cascade_coordinator.py  Multi-inbound: joint CP-SAT
│   │   ├── ramp_coordinator.py
│   │   ├── dispatch_coordinator.py
│   │   └── comms_coordinator.py
│   ├── tier1/                      Strategic Supervisor
│   │   ├── playbooks.py            Known disruption patterns (no LLM)
│   │   └── supervisor.py           Orchestrator + LLM for novel events
│   ├── events/                     Kafka producers and consumers
│   └── api/main.py                 FastAPI — /scenario/run, /scenario/state, /ws/events
│
├── demo/
│   ├── seed_data.py                JFK hub: 5 flights, 40 bags, 12 connections
│   ├── scenario_runner.py          CLI demo (rich terminal output)
│   └── dashboard.py                Streamlit real-time UI
│
├── tests/                          61 tests, all passing
├── research/
│   ├── explainer-for-beginners.md  ← Start here if new to this domain
│   ├── airline-baggage-dcortex.md  Industry landscape + $5B problem
│   ├── agentic-system-design.md    Architecture pattern decision + tradeoffs
│   ├── tech-stack.md               Tech stack selection rationale
│   ├── architecture-revision.md   Why V1 used LLM wrong + the correct V2 design
│   └── remaining-workflows.md     8 disruption workflows — status, steps, build order
│
├── docker-compose.yml
├── Dockerfile.api / .worker / .dashboard
├── requirements.txt
├── requirements-deploy.txt
├── DEPLOY.md
└── IMPLEMENTATION_PLAN.md
```

---

## Tests

```bash
python -m pytest tests/ -v
```

75 tests, all passing. Deterministic logic (triage, tools, coordinators) needs no
mocking. The Strategic Supervisor's LLM path is mocked in the 3 tests that exercise
novel-event and conflict-arbitration scenarios.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'src'`**
Run from the project root with the venv active. The `.venv/Lib/site-packages/baggage.pth`
file registers the project root automatically.

**Docker Desktop not running**
Start Docker Desktop from the Start menu, wait for the whale icon to stop animating
(~30 seconds), then retry `docker compose up -d`.

**API not reachable on dashboard**
Start the API in a separate terminal: `uvicorn src.api.main:app --port 8000`.
Make sure `API_URL` in `.env` matches.

**Kafka consumer not processing events**
Confirm the worker is running (`python src/worker.py`) and topics were created.
Check `KAFKA_BOOTSTRAP_SERVERS` in `.env` matches the running Redpanda instance.

---

## Research & Design Decisions

| Document | What it covers |
|---|---|
| [Explainer for beginners](research/explainer-for-beginners.md) | The airline domain, why bags miss connections, the system in plain English, V1 vs V2 explained simply |
| [Industry landscape](research/airline-baggage-dcortex.md) | The $5B problem, current tech limitations, where dCortex fits |
| [Architecture decision](research/agentic-system-design.md) | Why Event-Driven Hierarchical Supervisor with DAG execution, why other patterns fail |
| [Tech stack](research/tech-stack.md) | Why LangGraph over CrewAI/AutoGen, why Kafka over RabbitMQ/Redis |
| [Architecture revision](research/architecture-revision.md) | Why V1 used an LLM incorrectly, the correct tier-based design, CP-SAT model specification |

---

*Built with LangGraph · OR-Tools CP-SAT · Gemini · Redpanda · FastAPI · Streamlit*
