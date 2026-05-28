"""Kafka consumer — routes events from Redpanda to the Tier 1 supervisor.

One consumer group per deployment. The supervisor processes each event
synchronously (it internally fans out to domain coordinators in threads).
"""
from __future__ import annotations

import json
import signal
import threading
from typing import Any

from confluent_kafka import Consumer, KafkaError

from src.config import settings
from src.events.kafka_config import consumer_config
from src.events.topics import Topics
from src.events.producer import EventProducer
from src.models import DisruptionEvent, DisruptionType, Severity


DELAY_EVENT_TOPICS = [Topics.FLIGHT_DELAYS, Topics.GATE_CHANGES, Topics.CANCELLATIONS]

_TYPE_MAP = {
    Topics.FLIGHT_DELAYS: DisruptionType.FLIGHT_DELAY,
    Topics.GATE_CHANGES: DisruptionType.GATE_CHANGE,
    Topics.CANCELLATIONS: DisruptionType.CANCELLATION,
}


class SupervisorConsumer:
    """Polls Redpanda and dispatches each event to the supervisor."""

    def __init__(
        self,
        group_id: str = "baggage-supervisor",
        bootstrap_servers: str | None = None,
        auto_offset_reset: str = "latest",
    ):
        self._consumer = Consumer(consumer_config(group_id, auto_offset_reset))
        self._producer = EventProducer()
        self._running = False
        self._stop_event = threading.Event()

    def start(self, topics: list[str] | None = None) -> None:
        """Subscribe and start polling (blocking)."""
        topics = topics or DELAY_EVENT_TOPICS
        self._consumer.subscribe(topics)
        self._running = True
        print(f"[CONSUMER] Subscribed to: {topics}")

        try:
            while self._running and not self._stop_event.is_set():
                msg = self._consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    print(f"[CONSUMER] Error: {msg.error()}")
                    continue
                self._handle(msg)
        finally:
            self._consumer.close()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()

    def _handle(self, msg) -> None:
        try:
            payload: dict[str, Any] = json.loads(msg.value().decode("utf-8"))
            topic = msg.topic()

            event_type = _TYPE_MAP.get(topic, DisruptionType.FLIGHT_DELAY)
            flight_id = (
                payload.get("flight_id") or
                payload.get("event_id", "")
            )

            event = DisruptionEvent(
                event_id=payload.get("event_id", ""),
                event_type=event_type,
                payload=payload,
                severity=Severity.HIGH,
                affected_flights=[flight_id] if flight_id else [],
            )

            from src.tier1.supervisor import supervisor
            result = supervisor.process(event)

            # Write all actions to audit topic
            for action in result.get("all_actions", []):
                self._producer.publish_audit({
                    **action,
                    "disruption_id": event.event_id,
                    "playbook": result.get("playbook", "REACT"),
                })
            self._producer.flush(timeout=2.0)

            print(
                f"[CONSUMER] {event_type} on {flight_id} → "
                f"{result.get('playbook', result.get('react_reasoning', 'REACT'))} "
                f"| {len(result.get('all_actions', []))} actions"
            )

        except Exception as exc:
            print(f"[CONSUMER] Handler error: {exc}")
