# Tech Stack for the Baggage Coordination Agentic System

## 1. Evaluation Criteria

The architecture we designed (Event-Driven Hierarchical Supervisor with DAG domain execution) makes specific demands on the stack. Every choice below is evaluated against these five constraints:

| Constraint | Why It Matters |
|---|---|
| **Hierarchical + DAG support** | Tier 1 supervisor → Tier 2 coordinators → Tier 3 executors with parallel DAG within domains |
| **Event-driven fan-out** | A single flight delay event must activate Baggage, Ramp, Dispatch, and Comms coordinators simultaneously |
| **Durable audit log** | Aviation regulations require full traceability of every decision and action |
| **State persistence + fault recovery** | Agents must resume from last checkpoint if they crash mid-disruption |
| **Sub-second reaction time** | Transfer windows are 2–3 minutes; the system must respond in seconds, not tens of seconds |

---

## 2. Framework Layer — LangGraph

**Decision: LangGraph**

LangGraph is the primary agent orchestration framework for all three tiers.

### Why LangGraph Wins

| Requirement | LangGraph | CrewAI | AutoGen |
|---|---|---|---|
| Hierarchical supervisor | Native (`langgraph-supervisor` package) | Role-based only | Conversation-based |
| DAG parallel execution | Native (parallel node execution in StateGraph) | Sequential/hierarchical only | Limited |
| State persistence | PostgreSQL checkpointer, time-travel debugging | ChromaDB, limited | Session-level only |
| Human-in-the-loop | Native interrupt/resume | Bolt-on | Supported |
| Observability | LangSmith (native, best-in-class) | Minimal | AutoGen Studio (improving) |
| Token cost per task | ~$0.04 | ~$0.06 (30–50% overhead from role prompts) | ~$0.09 (multi-turn overhead) |
| Production deployments | Klarna, LinkedIn, Uber, JPMorgan | Limited enterprise evidence | Research-heavy |

### Why Not CrewAI

CrewAI's role-based abstraction is well-suited for simple multi-agent tasks but inflates token cost by 30–50% compared to hand-tuned LangGraph graphs. For a system making hundreds of coordination decisions per hour across an airline's operation, that cost compounds. More critically, CrewAI lacks the explicit DAG parallel execution model our domain coordinators require — it either runs sequentially or via a hierarchical process, neither of which maps cleanly to our Tier 2 design.

### Why Not AutoGen

AutoGen's conversation-driven model ("agents talk to each other") is the wrong abstraction for operations coordination. Our Tier 2 domain coordinators need to execute a dependency graph of deterministic actions in response to a trigger event — not hold a multi-turn dialogue. AutoGen also has the highest per-task token cost (~$0.09) and the weakest debugging story for production incidents.

### Why Not Google ADK or AWS Strands

Both are strong frameworks. Google ADK is ahead on protocol support (A2A, MCP, AG-UI) and has first-class event-driven architecture. AWS Strands has excellent observability and native AWS integration. The deciding factor: **LangGraph is provider-agnostic**. Airline systems integrate with dozens of legacy vendors. A framework locked to GCP or AWS creates a deployment constraint that is incompatible with the heterogeneous reality of airport IT. LangGraph with Kafka runs anywhere.

### How LangGraph Maps to Our Architecture

```python
# Tier 1 — Strategic Supervisor (LangGraph StateGraph + supervisor pattern)
from langgraph_supervisor import create_supervisor
from langgraph.graph import StateGraph

tier1_supervisor = create_supervisor(
    agents=[baggage_coordinator, ramp_coordinator, dispatch_coordinator, comms_coordinator],
    model=claude_opus,   # strongest reasoning for novel disruptions
    prompt="You are the Operations Intelligence Layer..."
)

# Tier 2 — Domain Coordinator (StateGraph with parallel nodes = DAG)
domain_graph = StateGraph(BaggageCoordinatorState)
domain_graph.add_node("query_bhs", query_bhs_agent)
domain_graph.add_node("check_departure", check_departure_agent)
domain_graph.add_node("get_ramp_capacity", get_ramp_capacity_agent)
# These three nodes run in parallel (fan-out edge)
domain_graph.add_edge(START, ["query_bhs", "check_departure", "get_ramp_capacity"])
domain_graph.add_node("evaluate_feasibility", evaluate_feasibility_agent)
# Converge after parallel fetch
domain_graph.add_edge(["query_bhs", "check_departure", "get_ramp_capacity"], "evaluate_feasibility")
```

---

## 3. Event Bus — Apache Kafka

**Decision: Apache Kafka**

Kafka is the event bus connecting Tier 1, Tier 2, and external operational systems.

### Why Kafka Wins

| Requirement | Kafka | RabbitMQ | Redis Streams |
|---|---|---|---|
| Fan-out (many consumers, same event) | Native consumer groups | Limited; messages consumed once by default | Consumer groups supported |
| Durable audit log | Persistent, configurable retention (days/months) | Messages deleted after consumption | In-memory; limited durability |
| Event replay for fault recovery | Native (seek to offset) | Not supported | Supported with caveats |
| Ordered events per flight | Partitioned by flight ID | Per-queue ordering only | Per-stream ordering |
| Throughput at IROPS peak | Millions of msgs/sec | Thousands/sec | Hundreds of thousands/sec |
| Connector ecosystem | 100+ connectors (BHS, AODB, airline systems) | Limited | Minimal |

### Why Not RabbitMQ

RabbitMQ is a task queue, not an event log. When a flight delay event is consumed by the Baggage Coordinator, RabbitMQ deletes it. The Ramp Coordinator never sees it unless you duplicate the message. Worse: there is no replay. If a domain coordinator crashes mid-execution and restarts, it cannot re-read the triggering event. For aviation audit requirements (every decision must be traceable), the lack of a durable log is disqualifying.

### Why Not Redis Streams

Redis Streams has sub-millisecond latency (better than Kafka's low single-digit milliseconds) but operates in-memory with limited retention. An airline operation generates event data for months that must be retained for incident investigation. In-memory storage is not the right model. Redis does serve us elsewhere (see State Management below), but not as the primary event bus.

### Topic Design

```
ops.flights.delays          ← consumed by: Baggage, Ramp, Dispatch, Comms coordinators
ops.flights.gate-changes    ← consumed by: Ramp, Comms
ops.flights.cancellations   ← consumed by: all domain coordinators
ops.baggage.exceptions      ← consumed by: Tier 1, Comms
ops.baggage.carousel-assign ← consumed by: Comms
ops.ramp.crew-status        ← consumed by: Baggage, Dispatch
ops.equipment.alerts        ← consumed by: Equipment coordinator, Tier 1
ops.decisions.playbooks     ← Tier 1 → Domain coordinators (activation signal)
ops.decisions.conflicts     ← Tier 1 arbitration outputs
ops.audit.actions           ← ALL agents write every action taken here (immutable audit log)
```

Each flight gets its own partition key, ensuring all events for a given flight arrive in order to the same consumer.

---

## 4. LLM Selection Per Tier

The key insight from 2025/2026 production patterns: **use the right model for the right tier, not the same model everywhere**. Token cost and latency are multiplied by call volume, not just per-call cost.

| Tier | Role | Model | Reasoning |
|---|---|---|---|
| **Tier 1 — Novel disruptions** | Compound IROPS reasoning, cross-domain conflict arbitration | Claude Opus 4 | Highest reasoning quality for multi-step interdependency analysis; used infrequently (20% of cases) |
| **Tier 1 — Playbook matching** | Recognizing known disruption patterns and selecting playbook | Claude Sonnet 4.5 | Fast, lower cost; classification task not open-ended reasoning; used for 80% of tier 1 activations |
| **Tier 2 — Domain coordinators** | Building DAG plan within a domain, evaluating feasibility | Claude Sonnet 4.5 | Balance of reasoning quality vs latency vs cost; called many times per disruption |
| **Tier 3 — Execution agents** | API calls to BHS, load planning, AODB, notification systems | **No LLM** | Tier 3 agents are pure tool wrappers. All reasoning has already happened in Tier 2. Invoking an LLM to call an API is wasteful. |

### Why Claude Over GPT or Gemini for This Use Case

- **Tool use reliability**: Claude Sonnet and Opus consistently rank highest on tool-calling accuracy benchmarks (critical for Tier 2 DAG tool chains where a wrong tool call mid-chain corrupts downstream state)
- **Long context**: Operational state context (current flights, bag manifests, ramp schedules) can be large; Claude's 200k context window handles this without chunking
- **Instruction following**: Operations coordination requires strict adherence to playbook rules and constraint satisfaction — Claude's instruction following is most reliable for this
- **LangGraph native integration**: `langchain_anthropic.ChatAnthropic` is a first-class LangGraph node

---

## 5. State and Memory Stack

Four distinct memory needs, four different storage choices:

### 5.1 Operational State (Working Memory) — Redis

Real-time state shared across all agents: current flight statuses, active disruption contexts, bag locations, ramp crew assignments.

- **Why Redis**: Sub-millisecond reads, pub/sub for agent coordination signals, atomic operations for distributed locks (prevents two coordinators from double-acting on the same resource)
- **Data model**: Hash per flight (`flight:{id}:state`), sorted sets for time-ordered events, pub/sub channels for real-time signals between tiers

### 5.2 Durable Agent State (Checkpointing) — PostgreSQL + LangGraph Checkpointer

LangGraph's built-in checkpointer saves the full graph state at every node transition. If a domain coordinator crashes halfway through a DAG execution, it resumes from the last checkpoint.

- **Why PostgreSQL over SQLite**: Production multi-agent systems need concurrent reads/writes from multiple domain coordinators. SQLite's file locking is incompatible with this.
- **Bonus**: PostgreSQL checkpoints double as the audit trail for regulatory compliance — every agent state transition is persisted with a timestamp.

```python
from langgraph.checkpoint.postgres import PostgresSaver

checkpointer = PostgresSaver.from_conn_string(
    "postgresql://baggage_agent:...@postgres:5432/ops_state"
)
graph = domain_graph.compile(checkpointer=checkpointer)
```

### 5.3 Episodic Memory (Past Disruptions) — Qdrant

When Tier 1 encounters an unusual disruption, it queries past similar events: "what did we do last time a weather event caused 8 simultaneous connection failures at Hub X?"

- **Why Qdrant**: Best performance for high-read/write mixed workloads (disruptions are written frequently during IROPS and queried during novel events). Written in Rust — low latency overhead. Sub-50ms vector search required for real-time advisor role.
- **Why not pgvector**: pgvector on Postgres handles episodic memory fine at early scale, but Qdrant's native vector indexing (HNSW) outperforms pgvector at 100k+ episode vectors.

### 5.4 Semantic Memory (Domain Rules) — PostgreSQL

Connection time minima by airport pair, off-load constraints by aircraft type, SLA thresholds, playbook definitions. These are structured, relational, and change only via configuration updates — not a vector use case.

### Memory Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│                  Working Memory Layer                    │
│   Redis — flight states, ramp allocations, bag locs     │
│   Sub-ms reads, distributed locks, pub/sub signals      │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                 Checkpoint Layer                         │
│   PostgreSQL + LangGraph Checkpointer                   │
│   Agent state at every graph node, fault recovery        │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                 Episodic Memory Layer                    │
│   Qdrant — vector store of past disruption outcomes     │
│   "Find similar past events" for novel IROPS reasoning  │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                 Semantic Memory Layer                    │
│   PostgreSQL — domain rules, playbooks, SLAs            │
│   Structured queries, managed via config updates        │
└─────────────────────────────────────────────────────────┘
```

---

## 6. API and Service Layer — FastAPI

Each domain coordinator and the Tier 1 supervisor expose a FastAPI service:

- `/health` — Kubernetes liveness/readiness probes
- `/override` — HITL endpoint for human operator to inject a decision or cancel an in-progress action
- `/status/{disruption_id}` — Real-time status of an active disruption response
- `/replay/{disruption_id}` — Trigger replay from a checkpoint (incident investigation)
- `/metrics` — Prometheus scrape endpoint

FastAPI is chosen over Flask for its native async support (critical — domain coordinators are event consumers running concurrent coroutines) and automatic OpenAPI documentation (airline IT teams require formal API contracts).

---

## 7. Deployment — Kubernetes

**Why Kubernetes, not serverless**

LangGraph's checkpointer requires persistent connections to PostgreSQL. Serverless platforms (AWS Lambda, Cloud Run in per-request mode) have execution timeouts (typically 15 min max) and cold start latency that is incompatible with long-running agents. During a major IROPS event, a domain coordinator may run a continuous recovery loop for 2+ hours.

Kubernetes provides:
- **Per-tier independent scaling**: Baggage Coordinator can scale to 8 replicas during peak disruptions; Tier 3 execution agents scale to zero when idle (Knative)
- **Persistent volumes** for PostgreSQL and Qdrant
- **Kafka managed by Strimzi** (Kafka operator for Kubernetes)
- **Resource isolation** per domain: ramp operations getting a CPU spike doesn't starve dispatch

### Service Layout

```
k8s/
├── tier1/
│   └── ops-intelligence-deployment.yaml    (2 replicas, hot standby)
├── tier2/
│   ├── baggage-coordinator-deployment.yaml (auto-scales 1–8)
│   ├── ramp-coordinator-deployment.yaml    (auto-scales 1–6)
│   ├── dispatch-coordinator-deployment.yaml
│   └── comms-coordinator-deployment.yaml
├── tier3/
│   └── execution-agents-deployment.yaml    (Knative, scales to 0)
├── infra/
│   ├── kafka/                              (Strimzi operator)
│   ├── redis/                              (Redis Operator)
│   ├── postgres/                           (CloudNativePG)
│   └── qdrant/                             (Qdrant Helm chart)
└── observability/
    ├── otel-collector.yaml
    └── langsmith-forwarder.yaml
```

---

## 8. Observability — LangSmith + OpenTelemetry

### LangSmith (Primary — LangGraph native)

Every LangGraph node execution (Tier 1 reasoning, Tier 2 DAG steps, Tier 3 tool calls) is automatically traced in LangSmith. This gives:
- Full trace of each disruption response: which agents were invoked, what they decided, in what order, with what inputs/outputs
- Time-travel debugging: replay any disruption from any checkpoint
- Token usage and cost tracking per disruption event
- Latency breakdown per tier and per node

### OpenTelemetry (Cross-service spans)

Kafka consumer events, FastAPI request handling, Redis operations, and PostgreSQL queries are not LangGraph nodes — they need OpenTelemetry instrumentation to appear in the same trace as the LangGraph spans. The OTel collector forwards spans to LangSmith (which supports OTLP ingestion) and to Datadog or Grafana Tempo for infrastructure-level visibility.

### Alerting

| Alert | Condition | Escalation |
|---|---|---|
| Transfer window breach risk | Agent identifies <4 min to close connection, action not yet confirmed | Page ramp supervisor |
| Agent checkpoint lag | Agent hasn't checkpointed in >30s during active disruption | Auto-restart + alert ops team |
| Kafka consumer lag | Domain coordinator falling behind event stream | Auto-scale consumer replicas |
| Cross-domain conflict | Tier 1 conflict resolution takes >10s | Escalate to human AOCC officer |

---

## 9. Full Stack at a Glance

| Layer | Technology | Why |
|---|---|---|
| **Agent framework** | LangGraph | Hierarchical supervisor + DAG execution + best-in-class state persistence + LangSmith observability |
| **Event bus** | Apache Kafka (Strimzi on K8s) | Durable audit log + fan-out + replay + ordered partitions per flight |
| **Tier 1 LLM (novel)** | Claude Opus 4 | Best reasoning for compound IROPS; used sparingly |
| **Tier 1 LLM (playbooks)** | Claude Sonnet 4.5 | Fast, cost-efficient for pattern classification |
| **Tier 2 LLM** | Claude Sonnet 4.5 | Balance of reasoning + latency + cost for domain DAG planning |
| **Tier 3** | No LLM — pure tool calls | All reasoning complete by Tier 2; Tier 3 is I/O only |
| **Working memory** | Redis | Sub-ms shared state, distributed locks, pub/sub signals |
| **Checkpoint store** | PostgreSQL + LangGraph checkpointer | Fault recovery, audit trail, time-travel debugging |
| **Episodic memory** | Qdrant | Fast vector similarity for past disruption retrieval |
| **Domain rules** | PostgreSQL | Structured, queryable, config-managed |
| **API layer** | FastAPI (async) | HITL endpoints, health probes, Kubernetes-native |
| **Deployment** | Kubernetes + Knative | Long-running agents, per-tier scaling, Tier 3 scale-to-zero |
| **Observability** | LangSmith + OpenTelemetry | Full agent trace + infrastructure spans in one view |

---

## 10. Key Tradeoffs Accepted

### LangGraph over Google ADK
We accept: weaker protocol support (A2A, AG-UI) and more manual event-driven wiring.
We gain: provider-agnostic deployment (no GCP lock-in), the most mature production debugging story, and the largest community for troubleshooting novel issues in a new domain.

### Kafka over Redis Streams (event bus)
We accept: higher operational complexity (Kafka has more moving parts than Redis).
We gain: durable audit log for aviation compliance, true message replay for fault recovery, ordered partitions per flight, and 100+ connectors for legacy airline systems.

### Kubernetes over Serverless
We accept: higher DevOps overhead; serverless would be simpler to deploy initially.
We gain: support for long-running agents, persistent state connections, and per-tier autoscaling without execution timeouts. Serverless is fundamentally incompatible with LangGraph checkpointing and continuous event consumers.

### No LLM at Tier 3
We accept: Tier 3 becomes harder to extend with ad-hoc logic.
We gain: 3–5x speedup at the execution layer and a clean separation between reasoning (Tier 2 and above) and execution (Tier 3). Embedding LLM calls in execution agents would add latency at the worst possible point (the moment of action) and create a reasoning surface where there should only be deterministic I/O.

---

## Sources

- [LangGraph vs CrewAI vs AutoGen 2026 — Examcert](https://www.examcert.app/blog/langgraph-vs-crewai-vs-autogen-agent-frameworks-2026/)
- [Agentic Frameworks Deep Dive — Amine El Farssi](https://amineelfarssi.github.io/blog/agentic-frameworks-comparison/)
- [How Kafka Improves Agentic AI — Red Hat Developer](https://developers.redhat.com/articles/2025/06/16/how-kafka-improves-agentic-ai)
- [LangGraph Multi-Agent Orchestration 2025 — Latenode](https://latenode.com/blog/ai-frameworks-technical-infrastructure/langgraph-multi-agent-orchestration/langgraph-multi-agent-orchestration-complete-framework-guide-architecture-analysis-2025)
- [LangGraph Supervisor Patterns 2026 — Lifetides Hub](https://www.lifetideshub.com/langgraph-supervisor-patterns-2026/)
- [Vector Database Benchmarks 2026 — CallSphere](https://callsphere.ai/blog/vector-database-benchmarks-2026-pgvector-qdrant-weaviate-milvus-lancedb)
- [Best Database for AI Agents 2026 — PingCAP](https://www.pingcap.com/compare/best-database-for-ai-agents/)
- [AI at Scale: Serverless or Kubernetes — Medium](https://medium.com/kingfisher-technology/ai-at-scale-serverless-or-kubernetes-825e9e177d0c)
- [Agent Observability Platforms 2026 — Digital Applied](https://www.digitalapplied.com/blog/agent-observability-platforms-langsmith-langfuse-arize-2026)
- [Multi-Agent Frameworks for Enterprise 2026 — Adopt.ai](https://www.adopt.ai/blog/multi-agent-frameworks)
- [AI Agent Frameworks Compared 2026 — Knowlee](https://www.knowlee.ai/blog/agentic-ai-frameworks-comparison-2026)
- [Kafka vs RabbitMQ vs Redis Streams — Medium](https://medium.com/@sachin.backend.dev/kafka-vs-rabbitmq-vs-redis-streams-the-unexpected-winner-41f6f46c02ec)
- [Four Pillars of Agentic AI on Kubernetes — AAIF](https://aaif.io/blog/agentic-ai-infrastructure-on-kubernetes/)
