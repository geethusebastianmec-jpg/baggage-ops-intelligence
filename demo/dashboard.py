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
            "a flight arrives late and no one coordinates fast enough to get bags onto the connecting flight. "
            "Today a human AOCC coordinator handles this with four sequential phone calls. "
            "By the time all four are done, the window is gone."
        )
    with ib:
        st.markdown("### The Solution")
        st.markdown(
            "This system replaces those four phone calls with one automated coordinator that "
            "acts across all domains **simultaneously**, in under 3 seconds. "
            "It uses **deterministic triage** (pure math — no AI needed for the easy part), "
            "a **CP-SAT constraint solver** for crew contention, and "
            "**Gemini Pro only for genuinely novel situations** that no pre-written playbook covers."
        )
    with ic:
        st.markdown("### What You Can Do Here")
        st.markdown(
            "**Run the Hub Crisis scenario** to watch the system act in real time. "
            "Three flights arrive late simultaneously at JFK. 12 bags are at risk. "
            "The system detects which bags are physically impossible to save (pure math), "
            "rushes the ones that can make it, and pre-notifies every passenger — "
            "all before a human coordinator would finish their first phone call."
        )

st.divider()

# ── Measurement callout ────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
m1.metric("Bags recovered", "74%", "+40% vs manual",
          help="System recovers 74% of at-risk bags. Manual baseline: 34%. Source: demo/replay.py across 5 scenarios.")
m2.metric("Decision time", "2.5 s", "-177 s vs manual",
          help="Median time from event arrival to all actions dispatched. Manual baseline: ~3 minutes per phone call.")
m3.metric("Disruption types handled", "8", "all workflows built",
          help="Delay, gate change, cancellation, equipment failure, loading failure, crew shortage, security hold, network cascade.")
m4.metric("Tests passing", "83", "deterministic",
          help="All 83 tests pass without mocking the LLM. Triage and CP-SAT are deterministic — same input always produces same output.")

st.divider()

# ── Live Demo ─────────────────────────────────────────────────────────────────
st.markdown("## Live Demo — JFK Hub Crisis")
st.markdown(
    "Three inbound flights are delayed. Two outbound flights depart soon. "
    "The system must decide which bags can still make it and act before the departure windows close."
)

st.markdown("#### Current Flight Status")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("AA401  ORD → JFK", "DELAYED", "+32 min", delta_color="inverse",
          help="32-min delay. 7 bags connecting to AA501. 5 are in Zone B (8-min move time, slack=+17). 2 are in Zone D (26-min move time, slack=-1 — physically impossible).")
c2.metric("AA402  LAX → JFK", "DELAYED", "+18 min", delta_color="inverse",
          help="18-min delay. 3 bags in Zone B connecting to AA501. Move time 8 min, window 25 min, slack=+17. All recoverable.")
c3.metric("AA403  MIA → JFK", "DELAYED", "+11 min", delta_color="inverse",
          help="11-min delay. 2 bags in Zone C connecting to AA502. Move time 10 min, window 40 min, slack=+30. No action needed.")
c4.metric("AA501  JFK → LHR", "ON TIME", "departs in 25 min",
          help="London flight. 10 bags from AA401 and AA402 need to transfer here.")
c5.metric("AA502  JFK → CDG", "ON TIME", "departs in 40 min",
          help="Paris flight. 2 bags from AA403. Comfortable 30-min slack — no intervention required.")

st.caption(
    "**How the system decides:** For each bag, `slack = departure_window − physical_move_time`. "
    "Slack ≥ 0 → can be rushed. Slack < 0 → physically impossible. "
    "This is arithmetic, not an AI judgment. "
    "If more bags are recoverable than the crew can handle simultaneously, "
    "a CP-SAT solver picks the optimal subset."
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
    except Exception:
        st.error(f"Could not reach the backend API at `{API}`. Make sure all services are running.")
        return False


def _poll_state() -> dict | None:
    try:
        return requests.get(f"{API}/scenario/state", timeout=5).json()
    except Exception:
        return None


def _node_icon(node: str) -> str:
    icons = {
        "prepare_context": "🔍",
        "fetch_departure": "🕐",
        "fetch_ramp": "👷",
        "triage_and_optimize": "🧮",   # V2: deterministic triage + CP-SAT
        "close_loop": "✅",             # V2: confirming scan
        "route_bags": "🚀",
        "flag_missed": "❌",
        "check_crew": "👷",
        "pull_adjacent_crew": "🔄",    # V2: crew shortage — adjacent zone pull
        "assign_task": "🚜",
        "escalate": "⚠️",
        "decide_hold": "✈️",
        "fetch_load_plan": "📋",
        "fetch_departure_window": "🕐",
        "send_notifications": "📱",
        "notify_passenger": "📱",
        "notify_ops": "📢",
        "notify_baggage_service": "📢",
        "find_affected_bags": "🔍",
        "divert_bags": "↩️",
        "reassign_crew": "🔄",
        "update_load_plan": "📋",
        "find_all_bags": "🔍",
        "rebook_bags": "🎫",
        "offload_loaded": "📦",
        "notify_passengers": "📱",
        "locate_bag": "🔍",
        "check_flight": "✈️",
        "emergency_load": "🚨",
        "rebook_bag": "🎫",
        "rebook_on_next_flight": "🎫",
        "place_hold": "🔒",
        "escalate_to_authority": "🚨",
        "find_impacted_bags": "🔍",
        "reroute_bags": "↩️",
        "alert_maintenance": "🔧",
        "assess_impact": "🧮",
        "aggregate_cascade": "🌐",
        "joint_triage": "🧮",
        "joint_optimize": "⚡",
        "dispatch_all": "🚀",
    }
    for key, icon in icons.items():
        if key in node.lower():
            return icon
    return "🤖"


def _notif_icon(notif_type: str) -> str:
    return {"RECOVERED": "✅", "AT_RISK": "⚠️", "MISSED": "❌"}.get(notif_type, "📱")


# ── Agent activity + bag board ────────────────────────────────────────────────
left, right = st.columns([3, 2])

with left:
    st.markdown("#### Agent Activity Timeline")
    st.caption(
        "Each line is a real action taken by an AI agent — "
        "querying baggage systems, running triage arithmetic, "
        "opening exception routing, assigning ramp crew, or notifying passengers. "
        "No LLM is called for the feasibility decision — that is pure math."
    )

    if not st.session_state.running and not st.session_state.done:
        api_ok = _api_health()
        if not api_ok:
            st.warning(
                f"Backend API is not reachable at `{API}`. "
                "If running locally: `.venv/Scripts/uvicorn src.api.main:app --port 8000`"
            )
        st.markdown("")
        if st.button(
            "▶  Run Hub Crisis Scenario",
            type="primary",
            use_container_width=True,
            disabled=not api_ok,
            help="Publishes 3 flight delay events to Kafka. The worker agents process them and report back here.",
        ):
            if _trigger_scenario():
                st.session_state.running = True
                st.rerun()

    elif st.session_state.running:
        st.info(
            "⚙️  Agents coordinating: events published to Kafka → worker picks them up → "
            "Tier 1 triage (slack math) → CP-SAT if crew contended → "
            "actions dispatched + audit records published back. "
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
                    "\n\n".join(lines) if lines else "_Waiting for first Kafka message..._"
                )
                progress_slot.caption(
                    f"Actions completed: **{state.get('action_count', 0)}**  ·  "
                    f"Confirmed loaded: **{state.get('saved_count', 0)}**  ·  "
                    f"Missed: **{state.get('missed_count', 0)}**"
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


with right:
    st.markdown("#### Bag Outcome Board")
    st.caption("Final status of all 12 bags that had connecting flights.")

    if st.session_state.done:
        saved = st.session_state.saved
        missed = st.session_state.missed
        notifs = st.session_state.notifications
        total = len(saved) + len(missed)

        ca, cb, cc = st.columns(3)
        ca.metric("Confirmed loaded", len(saved), delta=f"+{len(saved)}",
                  help="BHS confirming scan received — bag physically on outbound aircraft.")
        cb.metric("Missed", len(missed), delta=f"-{len(missed)}", delta_color="inverse",
                  help="Physical move time exceeded departure window. Passengers pre-notified.")
        cc.metric("Notifications sent", len(notifs),
                  help="AT_RISK (rushing), RECOVERED (confirmed), MISSED — all automatic.")

        if total > 0:
            pct = int(len(saved) / total * 100)
            st.progress(pct / 100, text=f"Recovery rate: {pct}% of at-risk bags confirmed loaded")

        st.markdown("")
        if saved:
            with st.expander(f"✅  {len(saved)} bags confirmed loaded on outbound aircraft", expanded=True):
                for tag in saved:
                    st.markdown(f"- `{tag}` — exception routing → ramp sprint → confirming scan received")
        if missed:
            with st.expander(f"❌  {len(missed)} bags — move time exceeded departure window"):
                for tag in missed:
                    st.markdown(f"- `{tag}` — Zone D position, 26-min move time, window only 25 min")
        if notifs:
            with st.expander(f"📱  {len(notifs)} automatic passenger notifications"):
                for n in notifs:
                    icon = _notif_icon(n.get("type", ""))
                    label = {"RECOVERED": "bag confirmed on aircraft",
                             "AT_RISK": "bag being rushed — update to follow",
                             "MISSED": "bag missed connection — delivery arranged"}.get(n.get("type", ""), n.get("type", ""))
                    st.caption(f"{icon}  `{n['passenger_id']}`  ·  `{n['bag_tag']}`  —  {label}")

    elif st.session_state.running:
        state = _poll_state()
        if state:
            ca, cb = st.columns(2)
            ca.metric("Confirmed so far", state.get("saved_count", 0))
            cb.metric("Missed so far", state.get("missed_count", 0))
        st.caption("Updates every 2 seconds as agents complete their work.")
    else:
        st.markdown(
            "Once you run the scenario, you'll see:\n"
            "- Which bags were confirmed loaded on the outbound aircraft\n"
            "- Which bags' move time exceeded the departure window\n"
            "- All three notification types: AT_RISK → RECOVERED or MISSED\n"
            "- The recovery rate vs the at-risk count"
        )

st.divider()

# ── Human Override ─────────────────────────────────────────────────────────────
with st.expander("🎮  Human Override Panel  —  intervene in any agent decision"):
    st.caption(
        "In production, an airline operations controller can override any agent decision at any time. "
        "Decisions operate in Advisory → Semi-autonomous → Full autonomous modes. "
        "This demo is in full-autonomous mode — every action runs without human approval. "
        "Use this panel to inject a manual override into the live event stream."
    )
    oc1, oc2 = st.columns(2)
    with oc1:
        decision = st.selectbox(
            "Decision", ["HOLD", "DEPART", "ESCALATE"],
            help="HOLD = delay departure to wait for bags ($500/min). DEPART = let it go. ESCALATE = send to AOCC supervisor."
        )
        target = st.text_input("Target flight", "AA501")
    with oc2:
        operator = st.text_input("Operator ID", "OPS-001")
        note = st.text_area("Reason / note", height=68, placeholder="e.g. VIP passenger on AA401 — hold 3 min")
    if st.button("Submit Override", help="Injects this decision into the live event stream."):
        try:
            requests.post(f"{API}/override",
                          json={"decision": decision, "target": target,
                                "operator": operator, "note": note}, timeout=5)
            st.success(f"Override submitted — {decision} on {target} by {operator}")
        except Exception as exc:
            st.error(f"Could not reach API: {exc}")

# ── System capabilities ────────────────────────────────────────────────────────
st.divider()
with st.expander("📋  System Capabilities — all 8 disruption workflows"):
    st.markdown(
        "The Hub Crisis demo shows Workflow 1. The system handles 7 more disruption types "
        "with the same tier-based architecture."
    )
    st.markdown("""
| Workflow | Trigger | What happens |
|---|---|---|
| **W1: Flight delay** | Inbound delayed | Slack triage per bag → CP-SAT if crew contended → exception routing → confirming scan |
| **W2: Gate change** | Departure gate changes | Find bags sorted to old chute → BHS divert → crew reassignment → load plan update |
| **W3: Cancellation** | Flight cancelled | Find all bags → rebook on next flight ‖ off-load bags in hold → MISSED + ETA notify |
| **W4: Equipment failure** | Belt/scanner fails | Identify impacted bags → reroute to alternate BHS path → maintenance alert → re-triage |
| **W5: Loading failure** | Bag not loaded at origin | Locate bag → check if flight still at gate → emergency load or rebook |
| **W6: Crew shortage** | No ramp crew in zone | Check adjacent zones (B↔C↔D) → pull crew before escalating to AOCC |
| **W7: Security hold** | CT scanner flags bag | Place hold → parallel passenger + baggage service notify → HITL: cleared → rebook / rejected → law enforcement |
| **W8: Network cascade** | Multiple inbounds delay → same outbound | Joint CP-SAT across ALL bags under true shared crew constraint (prevents N coordinators overpromising) |
""")
    st.caption(
        "All workflows are deterministic (Tier 1 rules + Tier 2 CP-SAT). "
        "Gemini Pro is only invoked when a compound event matches no pre-written playbook."
    )

# ── How it works ───────────────────────────────────────────────────────────────
st.divider()
with st.expander("⚙️  How this works — architecture and tech stack"):
    ta, tb = st.columns(2)
    with ta:
        st.markdown("""
**What happens when you click the button:**

1. Dashboard POSTs to the **FastAPI** backend
2. API publishes 3 delay events to **Kafka** (Redpanda)
3. **Worker service** polls Kafka, receives events
4. **Tier 1 Supervisor** matches each event to a playbook — no LLM
5. Supervisor activates domain coordinators **in parallel**:
   - **Baggage Coordinator** — fetches bags, runs **Tier 1 triage** (`slack = window − move_time`), runs **CP-SAT** only if crew is contended, opens exception routing
   - **Ramp Coordinator** — checks crew, pulls from adjacent zone if needed, assigns task
   - **Dispatch Coordinator** — cost comparison: `bags × $150 vs hold × $500/min`
6. `close_loop` node: simulates confirming BHS scan → `CONFIRMED_LOADED` + RECOVERED notify
7. Every action published to Kafka audit topic → API streams to dashboard

**The key design principle:** Each question answered at the cheapest correct tier.
Feasibility is arithmetic (Tier 1), not an AI judgment (Tier 4).
        """)
    with tb:
        st.markdown("""
**Technology stack:**

| Layer | Technology | Role |
|---|---|---|
| Agent framework | **LangGraph** | DAG execution, hierarchical supervisor |
| Feasibility solver | **OR-Tools CP-SAT** | Optimal bag recovery under crew contention |
| LLM | **Gemini 1.5 Pro** | Novel compound events only — Tier 4 |
| Event bus | **Redpanda** (Kafka) | Durable audit log, fan-out, replay |
| Backend API | **FastAPI** | Scenario triggers, WebSocket stream |
| Frontend | **Streamlit** | This dashboard |
| Checkpoint store | **PostgreSQL** | LangGraph fault recovery |
| Working memory | **Redis** | Shared agent state |

**Measured improvement vs manual baseline:**

Across 5 replay scenarios (`python demo/replay.py`):
- System: **74%** bags recovered
- Manual baseline: **34%** bags recovered
- Improvement: **+40 percentage points**
- Decision time: **2.5 seconds** vs **~3 minutes** manual
        """)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("")
st.markdown(
    "<div style='text-align:center; color:#888; font-size:0.85rem; padding-bottom:1rem;'>"
    "Built by <strong>dCortex</strong> · Operational Superintelligence for Airlines"
    "</div>",
    unsafe_allow_html=True,
)
