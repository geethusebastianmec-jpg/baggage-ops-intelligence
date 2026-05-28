# Deployment Guide — Full Stack on Railway

## What gets deployed

| Service | What it does | Public URL |
|---|---|---|
| `baggage-dashboard` | Streamlit UI — the shareable link | `https://baggage-dashboard.up.railway.app` |
| `baggage-api` | FastAPI — triggers scenario, streams results | `https://baggage-api.up.railway.app` |
| `baggage-worker` | Kafka consumer — runs the AI agents | internal only |
| Postgres plugin | LangGraph checkpoint store | internal |
| Redis plugin | Working memory | internal |
| Redpanda Cloud | Kafka event bus | external managed |

---

## Step 1 — Push to GitHub

1. Go to **https://github.com/new** and create a new public repo called `baggage`
2. Copy the repo URL (e.g. `https://github.com/YOUR_USERNAME/baggage.git`)
3. Run these commands in your terminal:

```
cd c:\Users\geeth\OneDrive\Desktop\baggage
git remote add origin https://github.com/YOUR_USERNAME/baggage.git
git push -u origin master
```

---

## Step 2 — Get a Redpanda Cloud Kafka broker (free)

1. Go to **https://cloud.redpanda.com** → Sign up (free)
2. Create a new **Serverless** cluster (free tier)
3. Under **Security → Users**, create a user with `SCRAM-SHA-256`
4. Under **Networking**, copy the **Bootstrap server** URL
5. Note down:
   - Bootstrap server: `seed-xxxx.us-east-1.aws.redpanda.cloud:9092`
   - Username: `your-username`
   - Password: `your-password`

---

## Step 3 — Deploy on Railway

1. Go to **https://railway.app** → Login with GitHub
2. Click **New Project → Deploy from GitHub repo** → select `baggage`

### Add Postgres plugin
- In the project, click **+ New → Database → PostgreSQL**
- Note the `DATABASE_URL` variable it creates

### Add Redis plugin
- Click **+ New → Database → Redis**
- Note the `REDIS_URL` variable it creates

### Deploy the API service
- Click **+ New → GitHub Repo → baggage**
- In Settings → **Dockerfile Path**: `Dockerfile.api`
- In **Variables**, add:
  ```
  GOOGLE_API_KEY=AIza...your-key...
  KAFKA_BOOTSTRAP_SERVERS=seed-xxxx.us-east-1.aws.redpanda.cloud:9092
  KAFKA_SECURITY_PROTOCOL=SASL_SSL
  KAFKA_SASL_MECHANISM=SCRAM-SHA-256
  KAFKA_SASL_USERNAME=your-username
  KAFKA_SASL_PASSWORD=your-password
  POSTGRES_DSN=${{Postgres.DATABASE_URL}}
  REDIS_URL=${{Redis.REDIS_URL}}
  LLM_TIER2=gemini-2.0-flash
  ```
- In Settings → **Generate Domain** → copy the URL (e.g. `https://baggage-api-xxxx.up.railway.app`)

### Deploy the Worker service
- Click **+ New → GitHub Repo → baggage** (again)
- In Settings → **Dockerfile Path**: `Dockerfile.worker`
- In **Variables**, add the same env vars as the API above
- No public domain needed (worker is internal)

### Deploy the Dashboard service
- Click **+ New → GitHub Repo → baggage** (again)
- In Settings → **Dockerfile Path**: `Dockerfile.dashboard`
- In Settings → **Port**: `8501`
- In **Variables**, add:
  ```
  GOOGLE_API_KEY=AIza...your-key...
  API_URL=https://baggage-api-xxxx.up.railway.app   ← the API URL from above
  ```
- In Settings → **Generate Domain** → this is your shareable URL

---

## Step 4 — Share

Send the dashboard URL to whoever you want. They open it, click **Run Hub Crisis Scenario**, and watch the agents coordinate live through the full Kafka → worker → audit action → dashboard pipeline.

---

## How the full flow works

```
User clicks "Run Scenario" on dashboard
    ↓
Dashboard POSTs to baggage-api /scenario/run
    ↓
API seeds JFK hub data + publishes 3 DelayEvents to Redpanda Cloud
    ↓
baggage-worker polls Redpanda → receives each DelayEvent
    ↓
worker calls Tier 1 supervisor.process()
    ↓ (parallel via ThreadPoolExecutor)
    ├── Baggage Coordinator (LangGraph DAG + Gemini 2.0 Flash)
    ├── Ramp Coordinator
    └── Dispatch Coordinator
    ↓
Each ActionRecord published to ops.audit.actions (Redpanda)
    ↓
baggage-api background thread consumes ops.audit.actions
    ↓
Dashboard polls /scenario/state every 2s → shows live results
```

---

## Local full-stack test (before deploying)

Make sure Docker Desktop is running, then:

```
make up        # starts Redpanda + Postgres + Redis locally
make topics    # creates all 10 Kafka topics

# Terminal 1 — API
.venv\Scripts\uvicorn src.api.main:app --port 8000

# Terminal 2 — Worker
.venv\Scripts\python src/worker.py

# Terminal 3 — Dashboard
.venv\Scripts\python -m streamlit run demo/dashboard.py
```

Open http://localhost:8501 and click "Run Hub Crisis Scenario".
