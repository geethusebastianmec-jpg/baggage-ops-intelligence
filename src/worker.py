"""Baggage worker — entry point for the Kafka consumer service.

Polls ops.flights.delays (and gate-change / cancellation topics),
runs the Tier 1 supervisor for each event, and publishes all
ActionRecords to ops.audit.actions.

Start command:
  python src/worker.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import signal

from src.events.consumer import SupervisorConsumer
from src.events.producer import ensure_topics_exist


def main() -> None:
    print("[WORKER] Starting baggage supervisor consumer...")

    try:
        ensure_topics_exist()
        print("[WORKER] Kafka topics verified.")
    except Exception as exc:
        print(f"[WORKER] Topic creation warning (may already exist): {exc}")

    consumer = SupervisorConsumer(group_id="baggage-worker")

    def _shutdown(sig, frame):
        print("[WORKER] Shutting down...")
        consumer.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    consumer.start()
    print("[WORKER] Stopped.")


if __name__ == "__main__":
    main()
