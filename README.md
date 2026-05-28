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

## The Solution

This system replaces that manual coordination with a three-tier multi-agent architecture
that detects a disruption and simultaneously activates specialist agents across every affected
domain — all within the transfer window.

```
Flight delay detected
    ↓
Tier 1 — Strategic Supervisor (playbook match or Gemini Pro reasoning)
    ↓ activates in parallel
    ├─ Baggage Coordinator  (LangGraph DAG + Gemini Flash)
    │   queries BHS → evaluates feasibility → opens exception routing
    ├─ Ramp Coordinator
    │   checks crew → assigns exception transfer task
    └─ Dispatch Coordinator
        checks departure window → decides hold or depart
    ↓
ActionRecords published to Kafka → audit trail + dashboard
```

---

## Demo Scenario — The Hub Crisis

JFK hub. Three inbound flights delayed simultaneously. 12 bags at risk.

| Flight | Route | Delay | Connecting bags | Outbound |
|--------|-------|-------|-----------------|---------|
| AA401 | ORD → JFK | **+32 min** | 7 bags | AA501 (JFK → LHR, departs in 25 min) |
| AA402 | LAX → JFK | **+18 min** | 3 bags | AA501 (JFK → LHR, departs in 25 min) |
| AA403 | MIA → JFK | **+11 min** | 2 bags | AA502 (JFK → CDG, departs in 40 min) |

The minimum connection time at JFK is 25 minutes. AA401 and AA402 are breached or very tight.
AA403 is still safe. The system identifies this instantly and acts accordingly.

**Expected outcome:** 8 bags saved via exception routing, 2 flagged as truly missed
(passengers pre-notified automatically), AA403 bags require no action.

---

## What's Handled

Airline baggage disruptions come in many forms. Here's honest coverage of what this system handles today:

| Scenario | Status | Notes |
|---|---|---|
| **Flight delay → transfer misconnection** | ✅ Full | Core use case. BHS query → Gemini feasibility → exception routing + ramp crew + passenger notify (AT_RISK and MISSED). Covers 41% of all mishandling. |
| **Gate change** | 🟡 Partial | Playbook fires (Ramp + Comms activated). Coordinators receive the event but don't yet reroute bags/crew to the new gate. |
| **Flight cancellation** | 🟡 Partial | Playbook fires (Baggage + Dispatch + Comms). All bags correctly flagged unrecoverable. Passenger rebooking and alternate-flight routing not yet implemented. |
| **ATC / SLOT delay** | 🟡 Partial | Treated as a standard flight delay (DelayReason.ATC). Full delay pipeline runs. SLOT-specific hold windows not separately modelled. |
| **Mechanical delay** | 🟡 Partial | Treated as a flight delay. Works for delays with known duration. Does not handle open-ended "unknown duration" mechanical holds. |
| **Compound / novel event** | 🟡 Partial | ReAct fallback: Gemini Pro reasons about which coordinators to activate. Coverage depends on what data is available for those coordinators at runtime. |
| **Loading failure** | ❌ Not yet | Second biggest cause of mishandling (16%). Requires a different trigger — a bag never loaded at origin, detected at departure. No event type or coordinator for this yet. |
| **BHS equipment failure** | ❌ Not yet | Event type (`EQUIPMENT_FAILURE`) defined in models, no playbook matches it, Equipment Coordinator not built. |
| **Security hold on a bag** | ❌ Not yet | `ExceptionType.SECURITY_HOLD` exists in the model. No coordinator or event flow handles it. |
| **Ramp crew shortage** | ❌ Not yet | RampCoordinator escalates when no crew is available, but there's no proactive crew sourcing or crew-shortage event type. |
| **Network cascade detection** | ❌ Not yet | Individual delays handled one by one. No component detects when a chain of delays is forming across the hub and pre-empts downstream impact. |

### Passenger notifications

Every impacted passenger is notified automatically — no human needed:

| Situation | Notification sent |
|---|---|
| Bag is at risk but being actively handled via exception routing | `AT_RISK` — *"Our team is working to transfer your bag"* |
| Bag has missed the connection (window too short) | `MISSED` — *"Your bag missed your connection, delivery via next available flight"* |

The `RECOVERED` notification (confirming successful transfer) is generated by the tool layer but not yet triggered post-transfer since there's no inbound confirmation event from the ramp crew once a bag is physically loaded.

---

## Architecture

Three-tier **Event-Driven Hierarchical Supervisor** with **DAG execution** at the domain level.

```
┌──────────────────────────────────────────────┐
│  Tier 1 — Strategic Supervisor               │
│  Playbook matching (fast) + Gemini Pro        │
│  (novel/compound events)                     │
│  Conflict arbitration across domains          │
└──────────────┬───────────────────────────────┘
               │  events via Kafka
    ┌──────────┼──────────┬─────────────┐
    ▼          ▼          ▼             ▼
 Baggage    Ramp      Dispatch      Comms
Coordinator Coordinator Coordinator Coordinator
(LangGraph  (LangGraph  (LangGraph  (LangGraph
 DAG)        DAG)        DAG)        DAG)
    │
    ▼
 Tier 3 — Execution Agents (stateless tool wrappers)
 BHS · Load Plan · Ramp · Passenger Notify · AODB
```

Full architecture decision + tradeoff analysis: [`research/agentic-system-design.md`](research/agentic-system-design.md)

Full tech stack selection rationale: [`research/tech-stack.md`](research/tech-stack.md)

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Agent framework | **LangGraph** | Hierarchical supervisor + DAG parallel execution + checkpointing |
| LLM (Tier 2 + Tier 1 playbook) | **Gemini 2.0 Flash** | Fast, cost-efficient for domain coordination |
| LLM (Tier 1 novel events) | **Gemini 1.5 Pro** | Best reasoning for compound disruptions |
| Event bus | **Redpanda** (Kafka-compatible) | Durable audit log, fan-out, event replay |
| Backend API | **FastAPI** + WebSocket | Scenario triggers, live event streaming |
| Frontend | **Streamlit** | Real-time agent activity dashboard |
| Checkpoint store | **PostgreSQL** | LangGraph state persistence, fault recovery |
| Working memory | **Redis** | Shared agent state, sub-ms reads |

---

## Running the App

There are three ways to run this, from simplest to full stack.

### Option 1 — CLI demo (no Docker, no API key needed yet)

The fastest way to see the agents in action. Uses mocked LLM responses so nothing
costs money and nothing requires external services.

```bash
git clone https://github.com/YOUR_USERNAME/baggage.git
cd baggage

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# At minimum, add your GOOGLE_API_KEY to .env for real LLM calls.
# Leave it blank to run with mocked responses.

# Run the scenario
python demo/scenario_runner.py
```

You'll see a rich terminal output: 3 IROPS events fire, agents coordinate,
bags get saved or flagged, passengers notified.

---

### Option 2 — Streamlit dashboard (visual, no Docker)

```bash
# After completing Option 1 setup above:
python -m streamlit run demo/dashboard.py
```

Open **http://localhost:8501**. The dashboard talks to the FastAPI backend — start
that first in a second terminal:

```bash
uvicorn src.api.main:app --port 8000
```

Click **"Run Hub Crisis Scenario"** to watch the agents coordinate in real time.

---

### Option 3 — Full stack with Kafka + Postgres + Redis (Docker required)

This runs the complete event-driven architecture:

```bash
# Requires Docker Desktop to be running

# 1. Start all infrastructure services
docker compose up -d

# 2. Wait ~15 seconds, then create the Kafka topics
docker exec baggage_redpanda rpk topic create \
  ops.flights.delays ops.flights.gate-changes ops.flights.cancellations \
  ops.baggage.exceptions ops.ramp.crew-status ops.equipment.alerts \
  ops.decisions.conflicts ops.decisions.resolved ops.decisions.playbooks \
  ops.audit.actions --partitions 4 --replicas 1

# 3. Terminal 1 — start the FastAPI backend
uvicorn src.api.main:app --port 8000

# 4. Terminal 2 — start the Kafka worker (runs the AI agents)
python src/worker.py

# 5. Terminal 3 — start the dashboard
python -m streamlit run demo/dashboard.py
```

Open **http://localhost:8501**. Now when you click Run, events flow through the full
Kafka pipeline: Dashboard → API → Redpanda → Worker (agents) → audit actions → Dashboard.

You can also watch the Redpanda console at **http://localhost:8080** to see messages
flowing through the topics in real time.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | Yes (for real LLM calls) | Google AI Studio key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `KAFKA_BOOTSTRAP_SERVERS` | Option 3 only | `localhost:19092` (local) or Redpanda Cloud URL |
| `POSTGRES_DSN` | Option 3 only | PostgreSQL connection string |
| `REDIS_URL` | Option 3 only | Redis connection URL |
| `API_URL` | Options 2 + 3 | URL of the FastAPI backend (default: `http://localhost:8000`) |
| `LLM_TIER2` | No | Gemini model for domain coordinators (default: `gemini-2.0-flash`) |
| `LLM_TIER1_NOVEL` | No | Gemini model for novel disruptions (default: `gemini-1.5-pro`) |

---

## Deploying (share a live URL)

The full deployment guide is in [`DEPLOY.md`](DEPLOY.md). The short version:

**Services used:**
- **Railway** — hosts the API, worker, and dashboard containers
- **Redpanda Cloud** (free tier) — managed Kafka
- **Railway Postgres** — managed PostgreSQL
- **Railway Redis** — managed Redis

**Steps:**
1. Push this repo to GitHub
2. Create a free Redpanda Cloud cluster → copy bootstrap URL + credentials
3. Deploy on [railway.app](https://railway.app) → New Project → Import from GitHub
4. Add PostgreSQL and Redis plugins
5. Deploy three services using `Dockerfile.api`, `Dockerfile.worker`, `Dockerfile.dashboard`
6. Set environment variables in Railway dashboard (Google API key + Kafka credentials)
7. Generate a public domain for the dashboard → share that URL

Full step-by-step: [`DEPLOY.md`](DEPLOY.md)

---

## Project Structure

```
baggage/
│
├── src/
│   ├── config.py               All settings (reads from .env)
│   ├── worker.py               Entry point for the Kafka consumer service
│   │
│   ├── models/                 Pydantic data models (Flight, Bag, events, etc.)
│   ├── tools/                  Tier 3: mock tool wrappers — BHS, load plan, ramp, AODB
│   │
│   ├── tier2/                  Domain coordinators (LangGraph DAGs)
│   │   ├── baggage_coordinator.py
│   │   ├── ramp_coordinator.py
│   │   ├── dispatch_coordinator.py
│   │   └── comms_coordinator.py
│   │
│   ├── tier1/                  Strategic supervisor
│   │   ├── playbooks.py        Known disruption patterns → fast path
│   │   └── supervisor.py       Orchestrates domain coordinators
│   │
│   ├── events/                 Kafka producers and consumers
│   │   ├── kafka_config.py     PLAINTEXT (local) / SASL_SSL (cloud) builder
│   │   ├── producer.py
│   │   ├── consumer.py
│   │   └── topics.py
│   │
│   └── api/
│       └── main.py             FastAPI — /scenario/run, /scenario/state, /ws/events
│
├── demo/
│   ├── seed_data.py            JFK hub: 5 flights, 40 bags, 12 connections
│   ├── scenario_runner.py      CLI demo (rich terminal output)
│   └── dashboard.py            Streamlit dashboard
│
├── tests/                      61 tests, all passing
│   ├── test_models.py
│   ├── test_tools.py
│   ├── test_tier2_baggage.py
│   ├── test_tier2_ramp.py
│   ├── test_tier1_supervisor.py
│   ├── test_events.py
│   └── test_scenario.py
│
├── research/                   Background research and design decisions
│   ├── airline-baggage-dcortex.md    Industry landscape + dCortex opportunity
│   ├── agentic-system-design.md      Architecture decision + tradeoff analysis
│   └── tech-stack.md                 Tech stack selection rationale
│
├── docker-compose.yml          Local: Redpanda + PostgreSQL + Redis
├── Dockerfile.api              FastAPI container
├── Dockerfile.worker           Worker container
├── Dockerfile.dashboard        Streamlit container
├── requirements.txt            Full local dependencies
├── requirements-deploy.txt     Lightweight cloud dependencies
├── DEPLOY.md                   Step-by-step Railway + Redpanda Cloud guide
└── IMPLEMENTATION_PLAN.md      Phase-by-phase build plan with acceptance criteria
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

61 tests, all passing. Tests mock the LLM so they run without an API key.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'src'`**
Make sure you're running commands from the project root (`baggage/`) with the
virtual environment activated. The `.venv/Lib/site-packages/baggage.pth` file
registers the project root automatically when the venv is active.

**Docker Desktop not running**
The `docker compose up` command requires Docker Desktop to be open. Start it from
the Start menu and wait for the whale icon to stop animating (~30 seconds), then retry.

**API not reachable on dashboard**
The dashboard expects the API at the URL in `API_URL` (default `http://localhost:8000`).
Start the API in a separate terminal with `uvicorn src.api.main:app --port 8000`.

**Kafka consumer not processing events**
Make sure the worker is running (`python src/worker.py`) and that the topics were
created (`make topics`). Check that `KAFKA_BOOTSTRAP_SERVERS` in `.env` matches
where Redpanda is actually running.

---

## Research & Design Decisions

The research behind this project is fully documented:

- **[Industry landscape](research/airline-baggage-dcortex.md)** — current state of baggage handling, the $5B problem, and where dCortex fits
- **[Architecture decision](research/agentic-system-design.md)** — why Event-Driven Hierarchical Supervisor with DAG execution, and why every other pattern was rejected
- **[Tech stack](research/tech-stack.md)** — why LangGraph over CrewAI/AutoGen, why Kafka over RabbitMQ/Redis Streams, why Gemini for this use case

---

*Built with LangGraph · Gemini · Redpanda · FastAPI · Streamlit*
