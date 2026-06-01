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
| BA-006, BA-007 | Zone D | 22 min | **+3 min** | Physically impossible ❌ |
| BA-008 → BA-010 (AA402) | Zone B | 8 min | **+7 min** | RUSH ✅ |
| BA-011, BA-012 (AA403) | Zone C | 10 min | **+30 min** | No action needed ✅ |

**Outcome:** 8 bags saved, 2 missed, 2 no-action. All affected passengers notified
automatically — no human needed.

---

## What's Handled

| Scenario | Status | Notes |
|---|---|---|
| **Flight delay → transfer misconnection** | ✅ Full | Deterministic triage (Tier 1) + CP-SAT for contention (Tier 2). AT_RISK and MISSED passenger notifications. Covers 41% of all mishandling. |
| **Gate change** | 🟡 Partial | Playbook fires (Ramp + Comms activated). Physical bag/crew rerouting to new gate not yet implemented in coordinators. |
| **Flight cancellation** | 🟡 Partial | All bags correctly flagged unrecoverable. Passenger rebooking and alternate-flight routing not yet implemented. |
| **ATC / SLOT delay** | 🟡 Partial | Treated as a standard flight delay. Full pipeline runs. SLOT-specific hold windows not separately modelled. |
| **Mechanical delay** | 🟡 Partial | Treated as a flight delay. Works for delays with known duration. Open-ended holds not handled. |
| **Compound / novel event** | 🟡 Partial | Gemini Pro reasons about which coordinators to activate. Once activated, all coordinator logic is deterministic. |
| **Loading failure** | ❌ Not yet | 16% of all mishandling. Different trigger — bag never loaded at origin. No event type or coordinator yet. |
| **BHS equipment failure** | ❌ Not yet | Event type defined in models, no playbook, no Equipment Coordinator built. |
| **Security hold on a bag** | ❌ Not yet | Model field exists (`ExceptionType.SECURITY_HOLD`). No coordinator or event flow. |
| **Ramp crew shortage** | ❌ Not yet | RampCoordinator escalates when no crew is available, but no proactive crew sourcing. |
| **Network cascade detection** | ❌ Not yet | Individual delays handled. No component detects forming cascades across the hub. |

### Passenger notifications

Every impacted passenger is notified automatically:

| Situation | Notification |
|---|---|
| Bag is at risk but being actively rushed | `AT_RISK` — *"Our team is working to transfer your bag"* |
| Bag physically cannot make the connection | `MISSED` — *"Your bag missed your connection, delivery via next available flight"* |

The `RECOVERED` confirmation (bag successfully loaded on the outbound) is not yet triggered —
it requires a confirming scan from the ramp crew, which is not yet wired.

---

## Architecture

**Event-Driven Hierarchical Supervisor** with per-domain **LangGraph DAGs**.
Each coordinator uses the correct decision tier internally — no LLM in the feasibility path.

```
┌─────────────────────────────────────────────────────────────┐
│  Strategic Supervisor (Tier 3 + Tier 4)                     │
│  Playbook registry (fast, no LLM) for known events          │
│  Gemini 1.5 Pro (Tier 4) for novel compound events only     │
│  Cross-domain conflict arbitration                          │
└────────────────┬────────────────────────────────────────────┘
                 │  events via Kafka
     ┌───────────┼───────────┬──────────────┐
     ▼           ▼           ▼              ▼
  Baggage     Ramp       Dispatch       Comms
 Coordinator Coordinator Coordinator  Coordinator
 (LangGraph) (LangGraph) (LangGraph)  (LangGraph)
     │
     ├─ Tier 1: slack triage (pure Python math)
     ├─ Tier 1: contention check (simple count)
     └─ Tier 2: CP-SAT optimizer (OR-Tools, if contended)
     │
     ▼
  Tool Layer (Tier 0 reads — no LLM)
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
│   │   ├── baggage_coordinator.py  Triage → contention → CP-SAT → dispatch
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
│   └── architecture-revision.md   Why V1 used LLM wrong + the correct V2 design
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

61 tests, all passing. Deterministic logic (triage, tools, coordinators) needs no
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
