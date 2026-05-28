"""Phase 7 acceptance tests — Kafka event bus wiring.

Tests run without a live Kafka broker (all producer/consumer calls mocked).
They verify: message serialisation, topic routing, and the consumer→supervisor
dispatch path.
"""
import json
from unittest.mock import MagicMock, patch, call

from src.events.topics import Topics, TOPIC_COORDINATOR_MAP
from src.models import DelayEvent, GateChangeEvent, DisruptionType, DisruptionEvent, Severity


# ── Topic registry ────────────────────────────────────────────────────────────

def test_all_required_topics_defined():
    required = [
        Topics.FLIGHT_DELAYS, Topics.GATE_CHANGES, Topics.CANCELLATIONS,
        Topics.BAGGAGE_EXCEPTIONS, Topics.AUDIT_ACTIONS, Topics.DECISIONS_CONFLICTS,
    ]
    for t in required:
        assert t, f"Topic {t!r} is empty string"


def test_topic_coordinator_map_covers_key_topics():
    assert "baggage_coordinator" in TOPIC_COORDINATOR_MAP[Topics.FLIGHT_DELAYS]
    assert "ramp_coordinator" in TOPIC_COORDINATOR_MAP[Topics.GATE_CHANGES]
    assert "dispatch_coordinator" in TOPIC_COORDINATOR_MAP[Topics.CANCELLATIONS]


# ── Producer serialisation ─────────────────────────────────────────────────────

@patch("src.events.producer.Producer")
def test_producer_publishes_delay_to_correct_topic(mock_producer_cls):
    mock_producer = MagicMock()
    mock_producer_cls.return_value = mock_producer

    from src.events.producer import EventProducer
    p = EventProducer(bootstrap_servers="localhost:19092")
    event = DelayEvent(flight_id="AA401", delay_minutes=32)
    p.publish_delay(event)

    mock_producer.produce.assert_called_once()
    call_kwargs = mock_producer.produce.call_args
    assert call_kwargs.kwargs["topic"] == Topics.FLIGHT_DELAYS
    assert call_kwargs.kwargs["key"] == b"AA401"

    payload = json.loads(call_kwargs.kwargs["value"].decode())
    assert payload["flight_id"] == "AA401"
    assert payload["delay_minutes"] == 32


@patch("src.events.producer.Producer")
def test_producer_publishes_gate_change(mock_producer_cls):
    mock_producer = MagicMock()
    mock_producer_cls.return_value = mock_producer

    from src.events.producer import EventProducer
    p = EventProducer(bootstrap_servers="localhost:19092")
    event = GateChangeEvent(
        flight_id="AA501", old_gate="B12", new_gate="C4",
        old_terminal="B", new_terminal="C",
    )
    p.publish_gate_change(event)

    call_kwargs = mock_producer.produce.call_args
    assert call_kwargs.kwargs["topic"] == Topics.GATE_CHANGES
    payload = json.loads(call_kwargs.kwargs["value"].decode())
    assert payload["new_gate"] == "C4"


@patch("src.events.producer.Producer")
def test_producer_publishes_audit_record(mock_producer_cls):
    mock_producer = MagicMock()
    mock_producer_cls.return_value = mock_producer

    from src.events.producer import EventProducer
    p = EventProducer(bootstrap_servers="localhost:19092")
    p.publish_audit({"node": "route_bags", "result": "2 bags routed", "disruption_id": "d-001"})

    call_kwargs = mock_producer.produce.call_args
    assert call_kwargs.kwargs["topic"] == Topics.AUDIT_ACTIONS


# ── Consumer dispatch ─────────────────────────────────────────────────────────

@patch("src.events.producer.Producer")
@patch("src.events.consumer.Consumer")
@patch("src.tier1.supervisor.supervisor")
def test_consumer_dispatches_to_supervisor(mock_supervisor, mock_consumer_cls, mock_producer_cls):
    """Consumer calls supervisor.process() with a correctly built DisruptionEvent."""
    mock_kafka_consumer = MagicMock()
    mock_consumer_cls.return_value = mock_kafka_consumer
    mock_producer_cls.return_value = MagicMock()

    # Simulate one message then stop
    mock_msg = MagicMock()
    mock_msg.error.return_value = None
    mock_msg.topic.return_value = Topics.FLIGHT_DELAYS
    mock_msg.value.return_value = json.dumps({
        "event_id": "evt-001",
        "flight_id": "AA401",
        "delay_minutes": 32,
    }).encode()

    mock_supervisor.process.return_value = {
        "playbook": "FLIGHT_DELAY_CRITICAL",
        "all_actions": [{"node": "route_bags", "result": "done", "coordinator": "baggage"}],
        "errors": {},
    }

    from src.events.consumer import SupervisorConsumer
    sc = SupervisorConsumer(bootstrap_servers="localhost:19092")

    # Call _handle directly (bypasses the polling loop)
    sc._handle(mock_msg)

    mock_supervisor.process.assert_called_once()
    event_arg: DisruptionEvent = mock_supervisor.process.call_args[0][0]
    assert event_arg.event_type == DisruptionType.FLIGHT_DELAY
    assert event_arg.payload["flight_id"] == "AA401"
