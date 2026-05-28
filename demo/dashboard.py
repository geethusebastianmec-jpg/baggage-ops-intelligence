"""Streamlit real-time dashboard — talks to the FastAPI backend via HTTP.

The dashboard does NOT run any agent logic itself.
All coordination happens in the worker + API services.

Flow:
  1. User clicks "Run Scenario"
  2. Dashboard POSTs to {API_URL}/scenario/run  → publishes events to Kafka
  3. Worker consumes events → runs supervisor → publishes audit actions to Kafka
  4. API consumes audit actions → populates state
  5. Dashboard polls {API_URL}/scenario/state every 2s → shows live results
"""
from __future__ import annotations

import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import requests
import streamlit as st

from src.config import settings

API = settings.api_url.rstrip("/")

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Baggage Ops Intelligence",
    page_icon="✈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Session state ──────────────────────────────────────────────────────────────
for key, default in [
    ("running", False), ("done", False),
    ("events", []), ("saved", []), ("missed", []),
    ("notifications", []), ("action_count", 0),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ── Header ─────────────────────────────────────────────────────────────────────
st.title("✈  Baggage Ops Intelligence — Hub Crisis Demo")
st.caption("JFK Hub  ·  3 simultaneous delays  ·  12 bags at risk  ·  Autonomous multi-agent coordination via Kafka")
st.divider()

# ── Flight status ──────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("AA401  ORD→JFK", "DELAYED", "+32 min", delta_color="inverse")
c2.metric("AA402  LAX→JFK", "DELAYED", "+18 min", delta_color="inverse")
c3.metric("AA403  MIA→JFK", "DELAYED", "+11 min", delta_color="inverse")
c4.metric("AA501  JFK→LHR", "ON TIME", "departs in 25 min")
c5.metric("AA502  JFK→CDG", "ON TIME", "departs in 40 min")
st.divider()


# ── API helpers ────────────────────────────────────────────────────────────────
def _api_health() -> bool:
    try:
        return requests.get(f"{API}/health", timeout=3).status_code == 200
    except Exception:
        return False


def _trigger_scenario() -> bool:
    try:
        r = requests.post(f"{API}/scenario/run", timeout=10)
        return r.status_code == 200
    except Exception as exc:
        st.error(f"Could not reach API at {API}: {exc}")
        return False


def _poll_state() -> dict | None:
    try:
        return requests.get(f"{API}/scenario/state", timeout=5).json()
    except Exception:
        return None


# ── Main layout ────────────────────────────────────────────────────────────────
left, right = st.columns([3, 2])

with left:
    st.subheader("Agent Activity")

    if not st.session_state.running and not st.session_state.done:
        api_ok = _api_health()
        if not api_ok:
            st.warning(f"API not reachable at `{API}`. Make sure the API service is running.")
        if st.button("▶  Run Hub Crisis Scenario", type="primary",
                     use_container_width=True, disabled=not api_ok):
            if _trigger_scenario():
                st.session_state.running = True
                st.rerun()

    elif st.session_state.running:
        st.info("Agents coordinating — polling for results every 2 seconds...")
        progress = st.empty()
        timeline = st.empty()

        for _ in range(60):          # poll for up to 2 min
            state = _poll_state()
            if state:
                recent = state.get("recent_events", [])
                lines = []
                for ev in recent:
                    t = ev.get("payload", {})
                    etype = ev.get("type", "")
                    if etype == "SCENARIO_STARTED":
                        lines.append("🚀 **Scenario started — events published to Kafka**")
                    elif etype == "AUDIT_ACTION":
                        node = t.get("node", t.get("coordinator", "agent"))
                        result = str(t.get("result", ""))[:90]
                        lines.append(f"&nbsp;&nbsp;`[{node}]` {result}")

                timeline.markdown("\n\n".join(lines) if lines else "_Waiting for first Kafka message..._")
                progress.caption(
                    f"Actions processed: **{state.get('action_count', 0)}** · "
                    f"Saved: **{state.get('saved_count', 0)}** · "
                    f"Missed: **{state.get('missed_count', 0)}**"
                )

                # Done when all 3 events have been processed (at least 3 audit actions)
                if state.get("action_count", 0) >= 3:
                    st.session_state.saved = state.get("saved", [])
                    st.session_state.missed = state.get("missed", [])
                    st.session_state.notifications = state.get("notifications", [])
                    st.session_state.action_count = state.get("action_count", 0)
                    st.session_state.events = recent
                    st.session_state.running = False
                    st.session_state.done = True
                    st.rerun()

            time.sleep(2)

        # Timeout fallback
        st.session_state.running = False
        st.warning("Timed out waiting for results. Check the worker service logs.")

    else:
        # Show collected event log
        for ev in st.session_state.events:
            etype = ev.get("type", "")
            payload = ev.get("payload", {})
            ts = ev.get("timestamp", "")[:19].replace("T", " ")
            if etype == "SCENARIO_STARTED":
                st.markdown(f"`{ts}` 🚀 **Scenario started — 3 events published to Kafka**")
            elif etype == "AUDIT_ACTION":
                node = payload.get("node", payload.get("coordinator", "agent"))
                result = str(payload.get("result", ""))[:100]
                st.markdown(f"`{ts}` &nbsp;&nbsp;`[{node}]` {result}")

        if st.button("↺  Run Again", use_container_width=True):
            for key in ["running", "done", "events", "saved", "missed", "notifications", "action_count"]:
                st.session_state[key] = [] if isinstance(st.session_state[key], list) else (False if isinstance(st.session_state[key], bool) else 0)
            st.rerun()


with right:
    st.subheader("Bag Board")

    if st.session_state.done:
        saved = st.session_state.saved
        missed = st.session_state.missed
        notifs = st.session_state.notifications

        ca, cb, cc = st.columns(3)
        ca.metric("Saved", len(saved), delta=f"+{len(saved)}")
        cb.metric("Missed", len(missed), delta=f"-{len(missed)}", delta_color="inverse")
        cc.metric("Notifications sent", len(notifs))

        if saved:
            st.success(f"Exception routing opened: {', '.join(saved)}")
        if missed:
            st.error(f"Missed connections: {', '.join(missed)}")
        if notifs:
            st.markdown("**Passenger notifications**")
            for n in notifs:
                icon = "❌" if n["type"] == "MISSED" else "⚠️"
                st.caption(f"{icon}  {n['passenger_id']}  ·  {n['bag_tag']}  ·  {n['type']}")
    elif st.session_state.running:
        state = _poll_state()
        if state:
            ca, cb = st.columns(2)
            ca.metric("Saved so far", state.get("saved_count", 0))
            cb.metric("Missed so far", state.get("missed_count", 0))
    else:
        st.info("Run the scenario to see bag outcomes here.")

st.divider()

# ── HITL Override ──────────────────────────────────────────────────────────────
with st.expander("Human Override Panel"):
    oc1, oc2 = st.columns(2)
    with oc1:
        decision = st.selectbox("Decision", ["HOLD", "DEPART", "ESCALATE"])
        target = st.text_input("Target flight", "AA501")
    with oc2:
        operator = st.text_input("Operator ID", "OPS-001")
        note = st.text_area("Note", height=68)
    if st.button("Submit Override"):
        try:
            requests.post(f"{API}/override",
                          json={"decision": decision, "target": target,
                                "operator": operator, "note": note}, timeout=5)
            st.success(f"Override submitted: {decision} on {target}")
        except Exception as exc:
            st.error(f"Failed: {exc}")

# ── Architecture info ──────────────────────────────────────────────────────────
with st.expander("How this works"):
    st.markdown("""
**Full event-driven stack:**

```
You click "Run Scenario"
    ↓
API publishes 3 DelayEvents → Kafka (Redpanda)
    ↓
Worker polls Kafka → runs Tier 1 Supervisor
    ↓ (parallel domain coordinators)
    ├─ Baggage Coordinator (LangGraph DAG + Gemini)
    ├─ Ramp Coordinator
    └─ Dispatch Coordinator
    ↓
ActionRecords published → Kafka ops.audit.actions
    ↓
API consumes audit actions → shown here in real-time
```

**Services:** Streamlit · FastAPI · Redpanda (Kafka) · PostgreSQL · Redis · Gemini 2.0 Flash
    """)
