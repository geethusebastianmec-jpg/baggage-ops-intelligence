"""Streamlit real-time demo dashboard.

Connects to the FastAPI WebSocket to stream agent activity live,
OR runs the scenario inline (no separate server needed).

Usage (standalone — runs scenario + shows results):
  streamlit run demo/dashboard.py

Usage (with live API server):
  # Terminal 1: uvicorn src.api.main:app --port 8000
  # Terminal 2: streamlit run demo/dashboard.py
"""
from __future__ import annotations

import json
import os
import sys
import time

# Ensure the project root is on sys.path so `src` is importable regardless of
# where Streamlit or Python is launched from.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import threading
from datetime import datetime
from typing import Any

import streamlit as st

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Baggage Ops Intelligence",
    page_icon="✈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── State keys ─────────────────────────────────────────────────────────────────
if "events" not in st.session_state:
    st.session_state.events = []
if "bag_statuses" not in st.session_state:
    st.session_state.bag_statuses = {}
if "notifications_sent" not in st.session_state:
    st.session_state.notifications_sent = []
if "scenario_done" not in st.session_state:
    st.session_state.scenario_done = False
if "scenario_started" not in st.session_state:
    st.session_state.scenario_started = False


# ── Header ─────────────────────────────────────────────────────────────────────
st.title("✈ Baggage Ops Intelligence — Hub Crisis Demo")
st.caption("JFK Hub · 3 simultaneous delays · 12 bags at risk · Autonomous multi-agent coordination")
st.divider()

# ── Flight status row ──────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("AA401 (ORD→JFK)", "DELAYED", "+32 min", delta_color="inverse")
col2.metric("AA402 (LAX→JFK)", "DELAYED", "+18 min", delta_color="inverse")
col3.metric("AA403 (MIA→JFK)", "DELAYED", "+11 min", delta_color="inverse")
col4.metric("AA501 (JFK→LHR)", "ON TIME", "departs 25 min")
col5.metric("AA502 (JFK→CDG)", "ON TIME", "departs 40 min")

st.divider()


def _run_scenario_in_background():
    """Runs the scenario and collects events into session state."""
    import json
    from unittest.mock import MagicMock, patch

    def _llm(verdict, recoverable, unrecoverable, reasoning):
        resp = MagicMock()
        resp.content = json.dumps({
            "verdict": verdict,
            "recoverable_bags": recoverable,
            "unrecoverable_bags": unrecoverable,
            "reasoning": reasoning,
        })
        m = MagicMock()
        m.invoke.return_value = resp
        return m

    # Patch LLM for all three events
    llm_responses = iter([
        _llm("PARTIAL",
             ["BA-001", "BA-002", "BA-003", "BA-004", "BA-005"],
             ["BA-006", "BA-007"],
             "5 bags in Zone B reachable via exception routing; BA-006/007 queue position too far."),
        _llm("RECOVERABLE",
             ["BA-008", "BA-009", "BA-010"],
             [],
             "All 3 bags reachable — 7 min remaining is sufficient with exception handling."),
    ])

    def _llm_factory(**kw):
        return next(llm_responses, _llm("RECOVERABLE", [], [], "No bags")())

    with patch("src.tier2.baggage_coordinator.ChatAnthropic", side_effect=_llm_factory):
        from demo.seed_data import load
        from src.models import DisruptionEvent, DisruptionType, Severity
        from src.tier1.supervisor import StrategicSupervisor
        from src.tools import store
        from src.tools.passenger_notify import PassengerNotifyTool
        from src.models import BagStatus

        load()

        sup = StrategicSupervisor()
        events_log = []

        def _log(msg: str, kind: str = "info"):
            events_log.append({"ts": datetime.now().strftime("%H:%M:%S"), "msg": msg, "kind": kind})

        for flight_id, delay, desc in [
            ("AA401", 32, "7 bags connecting to AA501 (LHR)"),
            ("AA402", 18, "3 bags connecting to AA501 (LHR)"),
            ("AA403", 11, "2 bags connecting to AA502 (CDG) — window safe"),
        ]:
            _log(f"▶ {flight_id} DELAYED +{delay} min — {desc}", "event")
            e = DisruptionEvent(
                event_type=DisruptionType.FLIGHT_DELAY,
                payload={"flight_id": flight_id, "delay_minutes": delay},
                severity=Severity.HIGH if delay >= 15 else Severity.MEDIUM,
                affected_flights=[flight_id],
            )
            r = sup.process(e)
            playbook = r.get("playbook", "REACT")
            coordinators = ", ".join(r.get("coordinators_activated", []))
            _log(f"  ↳ Playbook: {playbook} | Coordinators: {coordinators}", "detail")
            for action in r.get("all_actions", []):
                node = action.get("node", action.get("coordinator", "?"))
                result_text = str(action.get("result", ""))[:100]
                _log(f"    [{node}] {result_text}", "action")
            time.sleep(0.3)

        # Collect final state
        saved = [tag for tag, bag in store.BAGS.items()
                 if bag.status == BagStatus.EXCEPTION and bag.destination_flight]
        missed = [tag for tag, bag in store.BAGS.items() if bag.status == BagStatus.MISSED]
        notifs = PassengerNotifyTool.get_sent()

        return {
            "events": events_log,
            "bag_statuses": {
                tag: bag.status.value for tag, bag in store.BAGS.items()
                if bag.destination_flight
            },
            "notifications": notifs,
            "saved": saved,
            "missed": missed,
        }


# ── Main content ───────────────────────────────────────────────────────────────
left, right = st.columns([3, 2])

with left:
    st.subheader("Agent Activity Timeline")

    if not st.session_state.scenario_started:
        if st.button("▶ Run Hub Crisis Scenario", type="primary", use_container_width=True):
            st.session_state.scenario_started = True
            with st.spinner("Agents coordinating..."):
                outcome = _run_scenario_in_background()
            st.session_state.events = outcome["events"]
            st.session_state.bag_statuses = outcome["bag_statuses"]
            st.session_state.notifications_sent = outcome["notifications"]
            st.session_state.saved = outcome["saved"]
            st.session_state.missed = outcome["missed"]
            st.session_state.scenario_done = True
            st.rerun()
    else:
        for ev in st.session_state.events:
            ts = ev["ts"]
            msg = ev["msg"]
            kind = ev["kind"]
            if kind == "event":
                st.markdown(f"`{ts}` 🔴 **{msg}**")
            elif kind == "action":
                st.markdown(f"`{ts}` &nbsp;&nbsp;&nbsp;&nbsp;{msg}")
            else:
                st.markdown(f"`{ts}` &nbsp;&nbsp;{msg}")

with right:
    st.subheader("Bag Board")

    if st.session_state.scenario_done:
        saved = st.session_state.get("saved", [])
        missed = st.session_state.get("missed", [])
        notifs = st.session_state.get("notifications_sent", [])

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Saved", len(saved), delta=f"+{len(saved)}")
        col_b.metric("Missed", len(missed), delta=f"-{len(missed)}", delta_color="inverse")
        col_c.metric("Notifications", len(notifs))

        if saved:
            st.success(f"Routed via exception: {', '.join(saved)}")
        if missed:
            st.error(f"Missed connections: {', '.join(missed)}")
        if notifs:
            st.subheader("Passenger Notifications")
            for n in notifs:
                icon = "❌" if n["type"] == "MISSED" else "⚠️"
                st.caption(f"{icon} {n['passenger_id']} · {n['bag_tag']} · {n['type']}")
    else:
        st.info("Run the scenario to see bag outcomes here.")

st.divider()

# ── HITL Override panel ────────────────────────────────────────────────────────
with st.expander("Human Override Panel"):
    col_ov1, col_ov2 = st.columns(2)
    with col_ov1:
        decision = st.selectbox("Decision", ["HOLD", "DEPART", "ESCALATE"])
        target_flight = st.text_input("Target flight", "AA501")
    with col_ov2:
        operator = st.text_input("Operator ID", "OPS-001")
        note = st.text_area("Note", height=68)
    if st.button("Submit Override"):
        st.warning(f"Override submitted: {decision} on {target_flight} by {operator}")
        st.caption(f"Note: {note or '(none)'}")
