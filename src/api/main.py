"""FastAPI service — WebSocket event stream + HITL override endpoint.

The dashboard connects to /ws/events to receive live agent activity.
The scenario runner pushes events via push_event().
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Baggage Ops Intelligence API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory event queue — populated by push_event(), drained by WebSocket handler
_event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

# Snapshot of latest system state for the dashboard to read on connect
_state_snapshot: dict[str, Any] = {
    "flights": {},
    "bags": {},
    "actions": [],
    "notifications": [],
}


def push_event(event_type: str, payload: dict[str, Any]) -> None:
    """Called from scenario_runner or consumer to publish an event to the dashboard."""
    envelope = {
        "type": event_type,
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _event_queue.put_nowait(envelope)
    except asyncio.QueueFull:
        pass  # Non-blocking — dashboard just misses one event


def push_action(action: dict[str, Any]) -> None:
    _state_snapshot["actions"].append(action)
    push_event("ACTION", action)


def push_bag_update(bag_tag: str, status: str, coordinator: str = "") -> None:
    _state_snapshot["bags"][bag_tag] = {"status": status, "coordinator": coordinator}
    push_event("BAG_UPDATE", {"bag_tag": bag_tag, "status": status, "coordinator": coordinator})


def push_notification(passenger_id: str, bag_tag: str, notif_type: str, message: str) -> None:
    record = {"passenger_id": passenger_id, "bag_tag": bag_tag, "type": notif_type, "message": message}
    _state_snapshot["notifications"].append(record)
    push_event("NOTIFICATION", record)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/state")
def get_state() -> dict:
    """Return the current state snapshot for dashboard initial load."""
    from src.tools import store
    from src.tools.passenger_notify import PassengerNotifyTool
    return {
        "flights": {fid: f.model_dump() for fid, f in store.FLIGHTS.items()},
        "bags": {tag: b.model_dump() for tag, b in store.BAGS.items()},
        "actions": store.ACTION_LOG[-50:],
        "notifications": PassengerNotifyTool.get_sent(),
    }


@app.post("/override")
async def override(body: dict[str, Any]) -> dict:
    """Human-in-the-loop: inject a decision into the system."""
    push_event("OVERRIDE", {
        "decision": body.get("decision"),
        "target": body.get("target"),
        "operator": body.get("operator", "HUMAN"),
        "note": body.get("note", ""),
    })
    return {"status": "override_queued", "decision": body.get("decision")}


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await websocket.accept()
    # Send current state on connect
    await websocket.send_text(json.dumps({
        "type": "SNAPSHOT",
        "payload": await asyncio.get_event_loop().run_in_executor(None, lambda: {
            "flights": list({"AA401": "DELAYED+32", "AA402": "DELAYED+18",
                             "AA403": "DELAYED+11", "AA501": "ON_TIME", "AA502": "ON_TIME"}.items()),
        }),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))
    try:
        while True:
            try:
                event = await asyncio.wait_for(_event_queue.get(), timeout=30.0)
                await websocket.send_text(json.dumps(event, default=str))
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                await websocket.send_text(json.dumps({"type": "PING"}))
    except WebSocketDisconnect:
        pass
