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

Every question is answered at the cheapest tier that gets it right:

| Tier | Tool | Question answered |
|---|---|---|
| 0 | State store | Where is bag X right now? |
| 1 | Deterministic rules | Is this bag at risk? (`slack = window − move_time`) · Hold or depart cost comparison |
| 2a | **OR-Tools CP-SAT** | Which bags to rush under ramp crew contention? (resource assignment) |
| 2b | **OR-Tools MIP (CBC)** | Which flight for each missed bag? (multi-commodity flow, capacity-constrained) |
| 3 | Thin agent loop | Which of the above does this situation need, and in what order? |
| 4 | LLM (last resort) | Novel compound disruptions no playbook covers |

**Why two solvers at Tier 2?** Different problem structures require different solvers.
CP-SAT excels at resource assignment with logical constraints (crew capacity, priority rules).
MIP excels at network flow problems with capacity allocation and optimality guarantees.
See [`research/mip-vs-cpsat.md`](research/mip-vs-cpsat.md) for the full analysis.

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

**Outcome:** 8 bags saved, 2 missed, 4 no-action (AA403 bags including 2 interline).
All affected passengers notified automatically — no human needed.

---

## What's Handled

| Scenario | Status | Notes |
|---|---|---|
| **Flight delay → transfer misconnection** | ✅ Full | Slack triage (Tier 1) + CP-SAT for contention (Tier 2) + confirming scan feedback loop. Full AT_RISK → RECOVERED / MISSED notification lifecycle. Covers 41% of all mishandling. |
| **Gate change** | ✅ Full | `gate_change_coordinator`: finds bags sorted to old gate, BHS divert command, crew reassignment, load plan update, passenger notification. |
| **Loading failure at origin** | ✅ Full | `loading_failure_coordinator`: locate bag → check flight at gate → emergency load if time permits, else rebook on next flight + MISSED notification. Covers 16% of mishandling. |
| **BHS equipment failure** | ✅ Full | `equipment_coordinator`: identify impacted bags in failed zone, reroute to alternate BHS path, alert maintenance, re-run triage for newly at-risk bags. |
| **Network cascade** | ✅ Full | `network_cascade_coordinator`: aggregates all at-risk bags across multiple simultaneous delayed inbounds, runs single joint CP-SAT under true shared crew constraint. Prevents N separate coordinators overpromising on the same crew. |
| **Flight cancellation** | ✅ Full | `cancellation_coordinator`: find all bags → [rebook on next flight ‖ off-load bags already in hold] → MISSED + rebooking ETA notification to every passenger. |
| **ATC / SLOT delay** | 🟡 Partial | Treated as a standard flight delay. Full delay pipeline runs. SLOT-specific ground stop windows not separately modelled. |
| **Mechanical delay** | 🟡 Partial | Treated as a flight delay. Works for delays with known duration. Open-ended "unknown duration" mechanical holds not handled. |
| **Compound / novel event** | 🟡 Partial | Gemini Pro selects which coordinators to activate. NETWORK_CASCADE playbook handles the most common compound case (multiple delayed inbounds). Truly novel situations use LLM routing. |
| **Security hold on a bag** | ✅ Full | `security_hold_coordinator`: place hold + notify → HITL gate → CLEARED (rebook) or REJECTED (escalate to law enforcement + compliance log). |
| **Ramp crew shortage** | ✅ Full | `ramp_coordinator` upgraded: checks adjacent zones (B↔C↔D) before escalating. Logs original vs reassigned zone. Escalates to AOCC only when no crew in any adjacent zone. |
| **Interline bag coordination** | ✅ Full | `interline_coordinator`: identifies cross-airline connections, sends IATA Type B alert to partner airline, alerts transfer desk. Flags bags for manual oversight even when slack is positive — no automated BHS control across airline boundaries. |
| **GSP (Ground Service Provider)** | ✅ Full | `GroundHandler` enum (AIRLINE, SWISSPORT, MENZIES, DNATA). `ramp_coordinator` routes task assignment to `GSPTool` for outsourced zones (slower ETA, probabilistic acceptance) vs airline-direct ramp control. |
| **Crew bag priority (IATA P1)** | ✅ Full | `TicketClass.CREW = 3.0` priority weight — deadheading/positioning crew bags given highest priority in CP-SAT and MIP rerouter per IATA standard. |
| **Revenue-class weighting** | ✅ Full | 13-entry `PRIORITY_WEIGHTS` table: ticket class × frequent flyer tier. FIRST/PLATINUM=2.8 → ECONOMY/NONE=1.0. Used by CP-SAT (T2a) and MIP rerouter (T2b). |

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
│  Playbook registry — 9 known disruption types, no LLM            │
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
   ├─ Tier 2a: CP-SAT if crew contended — which bags to rush (OR-Tools)
   ├─ Tier 2b: MIP if bag missed — which rerouting flight (OR-Tools CBC)
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
| Crew contention solver | **OR-Tools CP-SAT** | Tier 2a — which bags to rush under ramp crew capacity limit |
| Rerouting solver | **OR-Tools MIP (CBC)** | Tier 2b — which flight for each missed bag, capacity-constrained |
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
│   ├── models/                     Pydantic types — Flight, Bag, TicketClass, GroundHandler, etc.
│   ├── tools/                      Tier 0: BHS, load plan, ramp, AODB, GSP mock wrappers
│   ├── solver/                     Tier 1 + 2: triage, CP-SAT, and MIP
│   │   ├── triage.py               Tier 1: deterministic slack-based bag triage
│   │   ├── optimizer.py            Tier 2a: OR-Tools CP-SAT — which bags to rush
│   │   └── rerouter.py             Tier 2b: OR-Tools MIP (CBC) — which flight for missed bags
│   ├── tier2/                      Domain coordinators (LangGraph DAGs)
│   │   ├── baggage_coordinator.py         Delay: triage → CP-SAT → dispatch → close_loop
│   │   ├── cancellation_coordinator.py    Cancellation: MIP rebook + offload + notify
│   │   ├── gate_change_coordinator.py     Gate change: BHS divert + crew reassign
│   │   ├── loading_failure_coordinator.py Not loaded: emergency load or MIP rebook
│   │   ├── equipment_coordinator.py       Belt/scanner: reroute + maintenance alert
│   │   ├── network_cascade_coordinator.py Multi-inbound: joint CP-SAT
│   │   ├── interline_coordinator.py       Cross-airline: IATA Type B alert + transfer desk
│   │   ├── security_hold_coordinator.py   Security hold: HITL cleared/rejected gate
│   │   ├── ramp_coordinator.py            Ramp: direct + GSP routing + adjacent-zone fallback
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
│   ├── replay.py                   Measurement harness — system vs manual baseline
│   └── dashboard.py                Streamlit real-time UI
│
├── tests/                          94 tests, all passing
├── research/
│   ├── explainer-for-beginners.md      ← Start here if new to this domain
│   ├── airline-baggage-dcortex.md      Industry landscape + $5B problem
│   ├── agentic-system-design.md        Architecture pattern decision + tradeoffs
│   ├── tech-stack.md                   Tech stack selection rationale
│   ├── architecture-revision.md        Why V1 used LLM wrong + correct V2 design
│   ├── remaining-workflows.md          8 disruption workflows — status + build order
│   ├── mip-vs-cpsat.md                 When each solver is correct for baggage IROPS
│   ├── validation-and-gaps.md          dCortex direction validation + production gaps
│   └── dcortex-coverage-analysis.md   Full coverage table: what we built vs dCortex scope
│
├── docker-compose.yml
├── Dockerfile.api / .worker / .dashboard
├── requirements.txt
├── requirements-deploy.txt
├── DEPLOY.md
└── IMPLEMENTATION_PLAN.md
```

---

## Measurement

Run the replay harness to see system vs baseline statistics across 5 disruption scenarios:

```bash
python demo/replay.py
```

Sample output (actual results from the current codebase):

```
Total bags at risk:    35
System saved:          26  (74%)
Baseline saved:        12  (34%)
Improvement:           +40% bags recovered
Median decision time:  2.5 s  (vs ~3 min manual)
```

The baseline models a human AOCC coordinator who saves at most 3 bags per phone call
and handles one inbound at a time. The system activates all coordinators in parallel
and runs CP-SAT optimization across all at-risk bags simultaneously.

---

## Tests

```bash
python -m pytest tests/ -v
```

94 tests, all passing. Deterministic logic (triage, CP-SAT, MIP, coordinators) needs no
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
| [MIP vs CP-SAT](research/mip-vs-cpsat.md) | When each solver is correct for baggage IROPS; hybrid Tier 2a/2b architecture |

---

*Built with LangGraph · OR-Tools CP-SAT + MIP · Gemini · Redpanda · FastAPI · React*
