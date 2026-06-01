"""FastAPI service.

Responsibilities:
  1. POST /scenario/run   — seeds data + publishes 3 delay events to Kafka
  2. GET  /scenario/state — current bag/action snapshot (polled by dashboard)
  3. WS   /ws/events      — streams audit actions as they arrive from Kafka
  4. POST /override       — HITL decision injection

On startup a background thread polls ops.audit.actions and pushes each record
into an asyncio Queue that the WebSocket handler drains.
"""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Baggage Ops Intelligence API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Shared in-memory state ────────────────────────────────────────────────────
_event_queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
_scenario_running: bool = False
_scenario_events: list[dict[str, Any]] = []


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _push(event_type: str, payload: dict[str, Any]) -> None:
    envelope = {"type": event_type, "payload": payload, "timestamp": _ts()}
    try:
        _event_queue.put_nowait(envelope)
    except asyncio.QueueFull:
        pass
    _scenario_events.append(envelope)


# ── Background Kafka audit consumer ──────────────────────────────────────────

def _start_audit_consumer() -> None:
    """Runs in a daemon thread; polls ops.audit.actions → pushes to WebSocket queue.

    Retries with exponential backoff if Kafka is unavailable or topics don't
    exist yet. Suppresses UNKNOWN_TOPIC errors (topic will appear after make topics).
    """
    import time as _time
    from confluent_kafka import Consumer, KafkaError
    from src.events.kafka_config import consumer_config
    from src.events.topics import Topics

    retry_delay = 5   # seconds between reconnect attempts
    max_delay = 60

    while True:
        try:
            consumer = Consumer(consumer_config("api-audit-reader", auto_offset_reset="latest"))
            consumer.subscribe([Topics.AUDIT_ACTIONS])
            print("[AUDIT-CONSUMER] subscribed to ops.audit.actions")
            retry_delay = 5  # reset on successful connect

            while True:
                msg = consumer.poll(timeout=0.2)
                if msg is None:
                    continue
                if msg.error():
                    code = msg.error().code()
                    if code == KafkaError._PARTITION_EOF:
                        continue
                    if code == KafkaError.UNKNOWN_TOPIC_OR_PART:
                        # Topic not created yet — wait quietly and retry
                        break
                    print(f"[AUDIT-CONSUMER] error: {msg.error()}")
                    continue
                try:
                    payload = json.loads(msg.value().decode("utf-8"))
                    _push("AUDIT_ACTION", payload)
                except Exception as exc:
                    print(f"[AUDIT-CONSUMER] parse error: {exc}")

        except Exception as exc:
            # Kafka not reachable — retry silently
            _ = exc  # suppress noisy traceback in startup logs

        _time.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, max_delay)


@app.on_event("startup")
async def _on_startup() -> None:
    # Try to create topics before the consumer starts — idempotent, safe to call repeatedly.
    try:
        from src.events.producer import ensure_topics_exist
        ensure_topics_exist()
        print("[API] Kafka topics verified.")
    except Exception as exc:
        print(f"[API] Kafka not reachable at startup — consumer will retry: {exc}")

    t = threading.Thread(target=_start_audit_consumer, daemon=True)
    t.start()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "scenario_running": _scenario_running}


@app.post("/scenario/run")
def run_scenario() -> dict:
    """Seed data and publish the 3 hub crisis events to Kafka."""
    global _scenario_running, _scenario_events
    _scenario_running = True
    _scenario_events = []

    from demo.seed_data import load
    from src.events.producer import EventProducer, ensure_topics_exist
    from src.models import DelayEvent, DelayReason
    from src.tools.passenger_notify import PassengerNotifyTool

    PassengerNotifyTool.clear()
    load()

    try:
        ensure_topics_exist()
    except Exception:
        pass  # topics may already exist

    producer = EventProducer()
    producer.publish_delay(DelayEvent(flight_id="AA401", delay_minutes=32, reason=DelayReason.WEATHER))
    producer.publish_delay(DelayEvent(flight_id="AA402", delay_minutes=18, reason=DelayReason.CONNECTING))
    producer.publish_delay(DelayEvent(flight_id="AA403", delay_minutes=11, reason=DelayReason.CONNECTING))
    producer.flush(timeout=5.0)

    _push("SCENARIO_STARTED", {"events_published": 3, "timestamp": _ts()})
    return {"status": "events_published", "count": 3}


@app.get("/scenario/state")
def get_state() -> dict:
    """Snapshot of current bags + recent audit events — polled by the dashboard."""
    from src.tools import store
    from src.tools.passenger_notify import PassengerNotifyTool
    from src.models import BagStatus

    bags = {}
    for tag, bag in store.BAGS.items():
        if bag.destination_flight:
            bags[tag] = {
                "status": bag.status.value,
                "passenger": bag.passenger_name,
                "origin_flight": bag.origin_flight,
                "destination_flight": bag.destination_flight,
            }

    saved = [t for t, b in store.BAGS.items()
             if b.status == BagStatus.EXCEPTION and b.destination_flight]
    missed = [t for t, b in store.BAGS.items() if b.status == BagStatus.MISSED]

    return {
        "scenario_running": _scenario_running,
        "bags": bags,
        "saved_count": len(saved),
        "missed_count": len(missed),
        "saved": saved,
        "missed": missed,
        "notifications": PassengerNotifyTool.get_sent(),
        "recent_events": _scenario_events[-30:],
        "action_count": len(store.ACTION_LOG),
    }


@app.post("/override")
def override(body: dict[str, Any]) -> dict:
    _push("OVERRIDE", {
        "decision": body.get("decision"),
        "target": body.get("target"),
        "operator": body.get("operator", "HUMAN"),
        "note": body.get("note", ""),
    })
    return {"status": "override_queued"}


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    await websocket.accept()
    # Send buffered events so late connectors catch up
    for ev in _scenario_events[-50:]:
        await websocket.send_text(json.dumps(ev, default=str))
    try:
        while True:
            try:
                event = await asyncio.wait_for(_event_queue.get(), timeout=25.0)
                await websocket.send_text(json.dumps(event, default=str))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "PING"}))
    except WebSocketDisconnect:
        pass
