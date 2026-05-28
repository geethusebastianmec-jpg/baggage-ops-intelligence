# Baggage Coordination Agentic System

An agentic AI system that coordinates airline baggage operations in real-time,
preventing transfer connection failures through autonomous multi-agent coordination.

## The Problem

Airline baggage mishandling costs the industry $5B/year. 41% of failures come from
transfer misconnections — a coordination failure, not a hardware failure. A flight
delay at a hub cascades into missed bags across multiple connecting flights, and today
a human coordinator in the AOCC handles this manually, one phone call at a time.

## The Solution

An Event-Driven Hierarchical Supervisor with DAG domain execution:

- **Tier 1** — Strategic Supervisor: monitors the full operation, detects disruptions,
  activates domain coordinators in parallel
- **Tier 2** — Domain Coordinators: Baggage, Ramp, Dispatch, Comms — each owns its
  domain and executes a parallel DAG of actions
- **Tier 3** — Execution Agents: stateless tool wrappers around BHS, load planning,
  ramp systems, passenger notifications

## Quick Start

**Prerequisites:** Docker, Python 3.11+, an Anthropic API key

```bash
# 1. Clone and install
git clone <repo>
cd baggage
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY at minimum

# 3. Start infrastructure
make up

# 4. Create Kafka topics
make topics

# 5. Run the demo
make demo

# 6. (Optional) Open the live dashboard in a second terminal
make dashboard   # → http://localhost:8501
```

## Demo Scenario: The Hub Crisis

JFK hub, 3 simultaneous flight delays, 12 bags at risk of missing connections:

| Flight | Delay | Bags at Risk |
|---|---|---|
| AA401 (ORD→JFK) | +32 min | 7 bags → AA501 (JFK→LHR) |
| AA402 (LAX→JFK) | +18 min | 3 bags → AA501 (JFK→LHR) |
| AA403 (MIA→JFK) | +11 min | 2 bags → AA502 (JFK→CDG) |

**Expected outcome:** System saves 8 bags autonomously, pre-notifies passengers
on the 2 that cannot make it. Total time: under 30 seconds.

## Architecture

See [research/agentic-system-design.md](research/agentic-system-design.md) for
the full architecture decision and tradeoff analysis.

See [research/tech-stack.md](research/tech-stack.md) for the full tech stack
selection rationale.

## Tech Stack

| Layer | Technology |
|---|---|
| Agent framework | LangGraph + langgraph-supervisor |
| Event bus | Redpanda (Kafka-compatible) |
| LLMs | Claude Opus 4 (Tier 1 novel) / Claude Sonnet 4.5 (Tier 1+2) |
| Working memory | Redis |
| Checkpoint store | PostgreSQL + LangGraph checkpointer |
| API | FastAPI + WebSocket |
| Demo UI | Streamlit |

## Project Structure

```
src/
├── models/        Data models: Flight, Bag, DisruptionEvent, etc.
├── tools/         Tier 3: mock tool wrappers (no LLM, deterministic)
├── tier2/         Domain coordinators (LangGraph DAGs)
├── tier1/         Strategic supervisor (playbooks + ReAct)
├── events/        Kafka producers and consumers
├── memory/        Redis and PostgreSQL clients
└── api/           FastAPI service with WebSocket

demo/
├── seed_data.py       JFK hub scenario data
├── scenario_runner.py Hub Crisis scenario script
└── dashboard.py       Streamlit real-time UI
```

## Implementation Phases

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full phase-by-phase
build plan with acceptance criteria for each phase.
