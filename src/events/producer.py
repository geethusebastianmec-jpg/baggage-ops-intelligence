"""Kafka event producer — publishes operational events to Redpanda topics."""
from __future__ import annotations
import json
from typing import Any

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

from src.config import settings
from src.events.topics import Topics
from src.models import DelayEvent, GateChangeEvent, CancellationEvent, ActionRecord, DisruptionEvent


class EventProducer:
    def __init__(self, bootstrap_servers: str | None = None):
        self._servers = bootstrap_servers or settings.kafka_bootstrap_servers
        self._producer = Producer({"bootstrap.servers": self._servers})

    def _publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None:
        self._producer.produce(
            topic=topic,
            key=(key or "").encode("utf-8"),
            value=json.dumps(payload, default=str).encode("utf-8"),
            callback=self._delivery_report,
        )
        self._producer.poll(0)

    @staticmethod
    def _delivery_report(err, msg) -> None:
        if err:
            print(f"[KAFKA] Delivery failed: {err}")

    def flush(self, timeout: float = 5.0) -> None:
        self._producer.flush(timeout)

    # ── Public API ────────────────────────────────────────────────────────────

    def publish_delay(self, event: DelayEvent) -> None:
        self._publish(Topics.FLIGHT_DELAYS, event.model_dump(), key=event.flight_id)

    def publish_gate_change(self, event: GateChangeEvent) -> None:
        self._publish(Topics.GATE_CHANGES, event.model_dump(), key=event.flight_id)

    def publish_cancellation(self, event: CancellationEvent) -> None:
        self._publish(Topics.CANCELLATIONS, event.model_dump(), key=event.flight_id)

    def publish_action(self, record: ActionRecord) -> None:
        self._publish(Topics.AUDIT_ACTIONS, record.model_dump(), key=record.disruption_id)

    def publish_disruption(self, event: DisruptionEvent) -> None:
        """Generic disruption event — routed by the supervisor consumer."""
        topic_map = {
            "FLIGHT_DELAY": Topics.FLIGHT_DELAYS,
            "GATE_CHANGE": Topics.GATE_CHANGES,
            "CANCELLATION": Topics.CANCELLATIONS,
        }
        topic = topic_map.get(event.event_type, Topics.FLIGHT_DELAYS)
        self._publish(topic, event.model_dump(), key=event.event_id)

    def publish_audit(self, record: dict[str, Any]) -> None:
        self._publish(Topics.AUDIT_ACTIONS, record)


def ensure_topics_exist(bootstrap_servers: str | None = None) -> None:
    """Create all required topics if they don't exist (idempotent)."""
    servers = bootstrap_servers or settings.kafka_bootstrap_servers
    admin = AdminClient({"bootstrap.servers": servers})
    all_topics = [
        Topics.FLIGHT_DELAYS, Topics.GATE_CHANGES, Topics.CANCELLATIONS,
        Topics.BAGGAGE_EXCEPTIONS, Topics.RAMP_CREW_STATUS, Topics.EQUIPMENT_ALERTS,
        Topics.DECISIONS_CONFLICTS, Topics.DECISIONS_RESOLVED,
        Topics.DECISIONS_PLAYBOOKS, Topics.AUDIT_ACTIONS,
    ]
    new_topics = [NewTopic(t, num_partitions=4, replication_factor=1) for t in all_topics]
    futures = admin.create_topics(new_topics)
    for topic, future in futures.items():
        try:
            future.result()
        except Exception:
            pass  # Topic already exists — safe to ignore
