"""Streamlit real-time dashboard — talks to the FastAPI backend via HTTP."""
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
    page_title="Baggage Ops Intelligence by dCortex",
    page_icon="🧳",
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


# ── Hero ───────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center; padding: 1.5rem 0 0.5rem 0;">
  <h1 style="font-size:2.4rem; margin-bottom:0.2rem;">🧳 Baggage Ops Intelligence</h1>
  <p style="font-size:1.1rem; color:#888; margin-top:0;">
    Autonomous AI coordination for airline baggage operations &nbsp;·&nbsp; Powered by dCortex
  </p>
</div>
""", unsafe_allow_html=True)

st.divider()

# ── What is this? ──────────────────────────────────────────────────────────────
with st.container():
    ia, ib, ic = st.columns(3)
    with ia:
        st.markdown("### The Problem")
        st.markdown(
            "Airlines mishandle **33 million bags per year** at a cost of **$5 billion**. "
            "The biggest cause — **41% of all failures** — is transfer misconnections: "
            "a flight arrives late and no one coordinates fast enough to get the bags onto the connecting flight. "
            "Today that coordination happens manually, one phone call at a time."
        )
    with ib:
        st.markdown("### The Solution")
        st.markdown(
            "This system replaces that manual coordination with a **multi-agent AI** that detects disruptions "
            "in real time, reasons about which bags are at risk, and simultaneously activates specialist agents "
            "across baggage handling, ramp operations, and passenger communications — "
            "all within the transfer window."
        )
    with ic:
        st.markdown("### What You Can Do Here")
        st.markdown(
            "**Run the Hub Crisis scenario** below to watch the system in action. "
            "Three flights arrive late simultaneously at JFK. "
            "12 bags are at risk of missing their connections to London and Paris. "
            "Hit the button and watch the AI agents coordinate the recovery — live, in real time."
        )

st.divider()

# ── Live scenario section label ────────────────────────────────────────────────
st.markdown("## Live Demo — JFK Hub Crisis")
st.markdown(
    "Three inbound flights are delayed. Two outbound flights depart soon. "
    "The system must decide which bags can still make it and act before the departure windows close."
)

# ── Flight status board ────────────────────────────────────────────────────────
st.markdown("#### Current Flight Status")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("AA401  ORD → JFK", "DELAYED", "+32 min", delta_color="inverse",
          help="32-minute delay. 7 bags connecting to AA501 (London). Window is breached.")
c2.metric("AA402  LAX → JFK", "DELAYED", "+18 min", delta_color="inverse",
          help="18-minute delay. 3 bags connecting to AA501 (London). Very tight window.")
c3.metric("AA403  MIA → JFK", "DELAYED", "+11 min", delta_color="inverse",
          help="11-minute delay. 2 bags connecting to AA502 (Paris). Window is still safe.")
c4.metric("AA501  JFK → LHR", "ON TIME", "departs in 25 min",
          help="London flight. 10 bags from AA401 and AA402 need to transfer here.")
c5.metric("AA502  JFK → CDG", "ON TIME", "departs in 40 min",
          help="Paris flight. 2 bags from AA403. Enough time — no action needed.")

st.caption(
    "**At risk:** 10 bags on AA401/AA402 have less than 25 minutes (the minimum connection time at JFK) "
    "to reach AA501 before it closes. The system must decide which are recoverable and act immediately."
)
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
        st.error(f"Could not reach the backend API at `{API}`. Make sure all services are running.")
        return False


def _poll_state() -> dict | None:
    try:
        return requests.get(f"{API}/scenario/state", timeout=5).json()
    except Exception:
        return None


# ── Agent activity + bag board ────────────────────────────────────────────────
left, right = st.columns([3, 2])

with left:
    st.markdown("#### Agent Activity Timeline")
    st.caption(
        "Each line below is a real action taken by an AI agent — "
        "querying baggage systems, evaluating feasibility with Gemini, "
        "opening exception routing, assigning ramp crew, or notifying passengers."
    )

    if not st.session_state.running and not st.session_state.done:
        api_ok = _api_health()
        if not api_ok:
            st.warning(
                f"Backend API is not reachable at `{API}`. "
                "If running locally, start the API with: `.venv/Scripts/uvicorn src.api.main:app --port 8000`"
            )
        st.markdown("")
        if st.button(
            "▶  Run Hub Crisis Scenario",
            type="primary",
            use_container_width=True,
            disabled=not api_ok,
            help="Publishes 3 flight delay events to Kafka. The worker agents will process them and report back here.",
        ):
            if _trigger_scenario():
                st.session_state.running = True
                st.rerun()

    elif st.session_state.running:
        st.info(
            "⚙️  Agents are coordinating across the full stack: "
            "events flowing through Kafka → worker picks them up → "
            "Gemini evaluates feasibility → actions published back. "
            "Refreshing every 2 seconds..."
        )
        progress_slot = st.empty()
        timeline_slot = st.empty()

        for _ in range(60):
            state = _poll_state()
            if state:
                recent = state.get("recent_events", [])
                lines = []
                for ev in recent:
                    payload = ev.get("payload", {})
                    etype = ev.get("type", "")
                    ts = ev.get("timestamp", "")[:19].replace("T", " ")
                    if etype == "SCENARIO_STARTED":
                        lines.append(f"`{ts}`  🚀  **3 delay events published to Kafka**")
                    elif etype == "AUDIT_ACTION":
                        node = payload.get("node", payload.get("coordinator", "agent"))
                        result = str(payload.get("result", ""))[:100]
                        icon = _node_icon(node)
                        lines.append(f"`{ts}`  {icon}  `[{node}]`  {result}")

                timeline_slot.markdown(
                    "\n\n".join(lines) if lines else "_Waiting for the first Kafka message to arrive..._"
                )
                progress_slot.caption(
                    f"Actions completed: **{state.get('action_count', 0)}**  ·  "
                    f"Bags saved: **{state.get('saved_count', 0)}**  ·  "
                    f"Bags missed: **{state.get('missed_count', 0)}**"
                )

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

        st.session_state.running = False
        st.warning("Timed out. The worker service may be starting up — try again in 30 seconds.")

    else:
        for ev in st.session_state.events:
            etype = ev.get("type", "")
            payload = ev.get("payload", {})
            ts = ev.get("timestamp", "")[:19].replace("T", " ")
            if etype == "SCENARIO_STARTED":
                st.markdown(f"`{ts}`  🚀  **3 delay events published to Kafka**")
            elif etype == "AUDIT_ACTION":
                node = payload.get("node", payload.get("coordinator", "agent"))
                result = str(payload.get("result", ""))[:100]
                icon = _node_icon(node)
                st.markdown(f"`{ts}`  {icon}  `[{node}]`  {result}")

        st.markdown("")
        if st.button("↺  Run the scenario again", use_container_width=True):
            for key in ["running", "done", "events", "saved", "missed", "notifications", "action_count"]:
                st.session_state[key] = [] if isinstance(st.session_state[key], list) \
                    else (False if isinstance(st.session_state[key], bool) else 0)
            st.rerun()


def _node_icon(node: str) -> str:
    icons = {
        "prepare_context": "🔍", "fetch_departure": "🕐", "fetch_ramp": "👷",
        "evaluate_feasibility": "🧠", "route_bags": "✅", "flag_missed": "❌",
        "check_crew": "👷", "assign_task": "🚜", "escalate": "⚠️",
        "decide_hold": "✈️", "fetch_load_plan": "📋", "send_notifications": "📱",
    }
    for key, icon in icons.items():
        if key in node.lower():
            return icon
    return "🤖"


with right:
    st.markdown("#### Bag Outcome Board")
    st.caption("Final status of all 12 bags that had connecting flights.")

    if st.session_state.done:
        saved = st.session_state.saved
        missed = st.session_state.missed
        notifs = st.session_state.notifications
        total = len(saved) + len(missed)

        ca, cb, cc = st.columns(3)
        ca.metric("Bags saved", len(saved), delta=f"+{len(saved)}",
                  help="Exception routing opened — ramp crew dispatched to transfer these bags.")
        cb.metric("Bags missed", len(missed), delta=f"-{len(missed)}", delta_color="inverse",
                  help="Window was too short. Passengers notified automatically.")
        cc.metric("Passengers notified", len(notifs),
                  help="Automatic SMS/app notifications sent without any human intervention.")

        if total > 0:
            pct = int(len(saved) / total * 100)
            st.progress(pct / 100, text=f"Recovery rate: {pct}% of at-risk bags saved")

        st.markdown("")
        if saved:
            with st.expander(f"✅  {len(saved)} bags saved via exception routing", expanded=True):
                for tag in saved:
                    st.markdown(f"- `{tag}` — exception routing opened, ramp crew assigned")
        if missed:
            with st.expander(f"❌  {len(missed)} bags could not make the connection"):
                for tag in missed:
                    st.markdown(f"- `{tag}` — window too short, passenger pre-notified")
        if notifs:
            with st.expander(f"📱  {len(notifs)} passenger notifications sent"):
                for n in notifs:
                    icon = "❌" if n["type"] == "MISSED" else "⚠️"
                    st.caption(f"{icon}  Passenger `{n['passenger_id']}` notified about bag `{n['bag_tag']}`")

    elif st.session_state.running:
        state = _poll_state()
        if state:
            ca, cb = st.columns(2)
            ca.metric("Saved so far", state.get("saved_count", 0))
            cb.metric("Missed so far", state.get("missed_count", 0))
        st.caption("Results update every 2 seconds as agents complete their work.")
    else:
        st.markdown(
            "Once you run the scenario, you'll see:\n"
            "- Which bags made it onto their connecting flights\n"
            "- Which bags missed the window\n"
            "- Which passengers were automatically notified\n"
            "- The overall recovery rate"
        )

st.divider()

# ── Human Override ─────────────────────────────────────────────────────────────
with st.expander("🎮  Human Override Panel  —  intervene in any agent decision"):
    st.caption(
        "In production, an airline operations controller can override any agent decision at any time. "
        "This panel simulates that capability. Submit an override and it is injected into the live event stream."
    )
    oc1, oc2 = st.columns(2)
    with oc1:
        decision = st.selectbox("Decision", ["HOLD", "DEPART", "ESCALATE"],
                                help="HOLD = delay the departure to wait for bags. DEPART = let it go. ESCALATE = send to human supervisor.")
        target = st.text_input("Target flight", "AA501", help="Which flight this decision applies to.")
    with oc2:
        operator = st.text_input("Operator ID", "OPS-001")
        note = st.text_area("Reason / note", height=68, placeholder="e.g. VIP passenger bags on AA401")
    if st.button("Submit Override", help="Injects this decision into the live event stream."):
        try:
            requests.post(f"{API}/override",
                          json={"decision": decision, "target": target,
                                "operator": operator, "note": note}, timeout=5)
            st.success(f"Override submitted — {decision} on {target} by {operator}")
        except Exception as exc:
            st.error(f"Could not reach API: {exc}")

# ── How it works ───────────────────────────────────────────────────────────────
st.divider()
with st.expander("⚙️  How this works — the full technical stack"):
    ta, tb = st.columns(2)
    with ta:
        st.markdown("""
**What happens when you click the button:**

1. The dashboard sends a request to the **FastAPI** backend
2. The API publishes 3 flight delay events to **Kafka** (Redpanda)
3. A background **worker service** picks up the events
4. The worker runs the **Tier 1 Strategic Supervisor** — it matches the events to pre-built playbooks
5. The supervisor activates domain coordinators **in parallel** using `ThreadPoolExecutor`:
   - **Baggage Coordinator** — queries the BHS, calls **Gemini 2.0 Flash** to decide which bags are recoverable, opens exception routing
   - **Ramp Coordinator** — checks crew availability, assigns exception transfer task
   - **Dispatch Coordinator** — decides whether to hold the departure or let it go
6. Every action is published back to Kafka as an **audit record**
7. The API streams audit records to this dashboard
        """)
    with tb:
        st.markdown("""
**The technology stack:**

| Layer | Technology |
|---|---|
| Agent framework | LangGraph (DAG execution) |
| LLM | Gemini 2.0 Flash / 1.5 Pro |
| Event bus | Redpanda (Kafka-compatible) |
| Backend API | FastAPI + WebSocket |
| Frontend | Streamlit |
| Checkpoint store | PostgreSQL |
| Working memory | Redis |

**Why this matters:**

The same architecture scales to a real airline operation — hundreds of simultaneous flights, thousands of bags, decisions made in seconds. The difference between today's manual AOCC coordination and this system is the difference between reacting in minutes and acting in seconds.
        """)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("")
st.markdown(
    "<div style='text-align:center; color:#888; font-size:0.85rem; padding-bottom:1rem;'>"
    "Built by <strong>dCortex</strong> · Operational Superintelligence for Airlines"
    "</div>",
    unsafe_allow_html=True,
)
