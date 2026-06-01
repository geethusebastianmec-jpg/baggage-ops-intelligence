"""End-to-end scenario tests — deterministic after V2 refactor.

No LLM mocking needed for the baggage coordinator (triage is now pure math).
Supervisor LLM is mocked only for the novel-event and conflict tests.
"""
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from src.tools import store
from src.tools.passenger_notify import PassengerNotifyTool
from src.models import BagStatus, DisruptionType, DisruptionEvent, Severity, Flight, FlightStatus


def test_scenario_aa401_partial():
    """AA401 (+32 min): Zone-B bags saved, Zone-D bags missed — pure triage."""
    from demo.seed_data import load
    load()
    PassengerNotifyTool.clear()

    from src.tier1.supervisor import StrategicSupervisor
    result = StrategicSupervisor().process(DisruptionEvent(
        event_type=DisruptionType.FLIGHT_DELAY,
        payload={"flight_id": "AA401", "delay_minutes": 32},
        severity=Severity.HIGH, affected_flights=["AA401"],
    ))

    assert result["errors"] == {}
    baggage = result["coordinator_results"].get("baggage_coordinator", {})
    assert baggage.get("feasibility_verdict") == "PARTIAL"
    assert set(baggage["recoverable_bag_tags"]) == {
        "BA-001", "BA-002", "BA-003", "BA-004", "BA-005"
    }
    assert set(baggage["unrecoverable_bag_tags"]) == {"BA-006", "BA-007"}

    for tag in ["BA-001", "BA-002", "BA-003", "BA-004", "BA-005"]:
        assert store.BAGS[tag].status == BagStatus.EXCEPTION
    for tag in ["BA-006", "BA-007"]:
        assert store.BAGS[tag].status == BagStatus.MISSED

    sent = PassengerNotifyTool.get_sent()
    assert len([n for n in sent if n["type"] == "MISSED"]) == 2
    assert len([n for n in sent if n["type"] == "AT_RISK"]) == 5


def test_scenario_aa402_recoverable():
    """AA402 (+18 min): all 3 Zone-B bags recoverable."""
    from demo.seed_data import load
    load()
    PassengerNotifyTool.clear()

    from src.tier1.supervisor import StrategicSupervisor
    result = StrategicSupervisor().process(DisruptionEvent(
        event_type=DisruptionType.FLIGHT_DELAY,
        payload={"flight_id": "AA402", "delay_minutes": 18},
        severity=Severity.HIGH, affected_flights=["AA402"],
    ))

    assert result["errors"] == {}
    baggage = result["coordinator_results"].get("baggage_coordinator", {})
    assert baggage.get("feasibility_verdict") == "RECOVERABLE"
    for tag in ["BA-008", "BA-009", "BA-010"]:
        assert store.BAGS[tag].status == BagStatus.EXCEPTION

    sent = PassengerNotifyTool.get_sent()
    assert len(sent) == 3
    assert all(n["type"] == "AT_RISK" for n in sent)


def test_scenario_aa403_no_action():
    """AA403 (+11 min): bags are not flagged at-risk, nothing happens."""
    from demo.seed_data import load
    load()
    PassengerNotifyTool.clear()

    from src.tier1.supervisor import StrategicSupervisor
    StrategicSupervisor().process(DisruptionEvent(
        event_type=DisruptionType.FLIGHT_DELAY,
        payload={"flight_id": "AA403", "delay_minutes": 11},
        severity=Severity.MEDIUM, affected_flights=["AA403"],
    ))

    assert store.BAGS["BA-011"].status == BagStatus.CHECKED_IN
    assert store.BAGS["BA-012"].status == BagStatus.CHECKED_IN
    assert len(PassengerNotifyTool.get_sent()) == 0


def test_seed_data_loads_correctly():
    from demo.seed_data import load
    load()
    assert len(store.FLIGHTS) == 5
    assert len([t for t, c in store.CONNECTIONS.items() if c]) == 12
    at_risk = [t for t, c in store.CONNECTIONS.items() if any(x.is_at_risk for x in c)]
    assert len(at_risk) == 10   # 7 AA401 + 3 AA402
    safe = [t for t, c in store.CONNECTIONS.items()
            if c and not any(x.is_at_risk for x in c)]
    assert len(safe) == 2       # BA-011, BA-012 (AA403)

    # Verify move times are set correctly in seed data
    ba006_conn = store.CONNECTIONS["BA-006"][0]
    assert ba006_conn.move_time_minutes == 26   # Zone D
    ba001_conn = store.CONNECTIONS["BA-001"][0]
    assert ba001_conn.move_time_minutes == 8    # Zone B
