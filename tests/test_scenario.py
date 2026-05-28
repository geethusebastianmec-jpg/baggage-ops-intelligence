"""Phase 8 acceptance tests — end-to-end scenario.

LLM is fully mocked. Verifies the correct outcome for all three events
in the Hub Crisis scenario: right bags saved, right bags missed,
right passengers notified.
"""
import json
from unittest.mock import MagicMock, patch

from src.tools import store
from src.tools.passenger_notify import PassengerNotifyTool
from src.models import BagStatus, DisruptionType, DisruptionEvent, Severity


def _llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = resp
    return mock_llm


@patch("src.tier2.baggage_coordinator.ChatAnthropic")
def test_scenario_aa401_partial(mock_llm_cls):
    """AA401 (+32 min) → 5 recoverable, 2 missed out of 7 bags."""
    from demo.seed_data import load
    load()
    PassengerNotifyTool.clear()

    mock_llm_cls.return_value = _llm_response(json.dumps({
        "verdict": "PARTIAL",
        "recoverable_bags": ["BA-001", "BA-002", "BA-003", "BA-004", "BA-005"],
        "unrecoverable_bags": ["BA-006", "BA-007"],
        "reasoning": "5 bags in BHS Zone B reachable; BA-006/007 too far in queue.",
    }))

    from src.models import DisruptionEvent, DisruptionType, Severity
    from src.tier1.supervisor import StrategicSupervisor
    sup = StrategicSupervisor()
    result = sup.process(DisruptionEvent(
        event_type=DisruptionType.FLIGHT_DELAY,
        payload={"flight_id": "AA401", "delay_minutes": 32},
        severity=Severity.HIGH, affected_flights=["AA401"],
    ))

    assert result["errors"] == {}
    baggage_result = result["coordinator_results"].get("baggage_coordinator", {})
    assert baggage_result.get("feasibility_verdict") == "PARTIAL"
    assert set(baggage_result["recoverable_bag_tags"]) == {"BA-001", "BA-002", "BA-003", "BA-004", "BA-005"}
    assert set(baggage_result["unrecoverable_bag_tags"]) == {"BA-006", "BA-007"}

    for tag in ["BA-001", "BA-002", "BA-003", "BA-004", "BA-005"]:
        assert store.BAGS[tag].status == BagStatus.EXCEPTION
    for tag in ["BA-006", "BA-007"]:
        assert store.BAGS[tag].status == BagStatus.MISSED

    sent = PassengerNotifyTool.get_sent()
    missed_notifs = [n for n in sent if n["type"] == "MISSED"]
    assert len(missed_notifs) == 2
    notified_tags = {n["bag_tag"] for n in missed_notifs}
    assert notified_tags == {"BA-006", "BA-007"}


@patch("src.tier2.baggage_coordinator.ChatAnthropic")
def test_scenario_aa402_recoverable(mock_llm_cls):
    """AA402 (+18 min) → all 3 bags recoverable."""
    from demo.seed_data import load
    load()
    PassengerNotifyTool.clear()

    mock_llm_cls.return_value = _llm_response(json.dumps({
        "verdict": "RECOVERABLE",
        "recoverable_bags": ["BA-008", "BA-009", "BA-010"],
        "unrecoverable_bags": [],
        "reasoning": "All 3 bags reachable via exception routing within window.",
    }))

    from src.tier1.supervisor import StrategicSupervisor
    sup = StrategicSupervisor()
    result = sup.process(DisruptionEvent(
        event_type=DisruptionType.FLIGHT_DELAY,
        payload={"flight_id": "AA402", "delay_minutes": 18},
        severity=Severity.HIGH, affected_flights=["AA402"],
    ))

    assert result["errors"] == {}
    baggage_result = result["coordinator_results"].get("baggage_coordinator", {})
    assert baggage_result.get("feasibility_verdict") == "RECOVERABLE"
    for tag in ["BA-008", "BA-009", "BA-010"]:
        assert store.BAGS[tag].status == BagStatus.EXCEPTION
    assert len(PassengerNotifyTool.get_sent()) == 0


def test_scenario_aa403_no_action():
    """AA403 (+11 min) → 2 bags safe, no at-risk connections, no LLM invoked."""
    from demo.seed_data import load
    load()
    PassengerNotifyTool.clear()

    # AA403 bags have is_at_risk=False in seed data
    # Coordinator should short-circuit with RECOVERABLE verdict and no LLM call
    with patch("src.tier2.baggage_coordinator.ChatAnthropic") as mock_llm:
        from src.tier1.supervisor import StrategicSupervisor
        sup = StrategicSupervisor()
        result = sup.process(DisruptionEvent(
            event_type=DisruptionType.FLIGHT_DELAY,
            payload={"flight_id": "AA403", "delay_minutes": 11},
            severity=Severity.MEDIUM, affected_flights=["AA403"],
        ))

    # LLM should not have been called (no at-risk bags)
    mock_llm.assert_not_called()
    # Bags untouched
    assert store.BAGS["BA-011"].status == BagStatus.CHECKED_IN
    assert store.BAGS["BA-012"].status == BagStatus.CHECKED_IN
    assert len(PassengerNotifyTool.get_sent()) == 0


def test_seed_data_loads_correctly():
    from demo.seed_data import load
    load()
    assert len(store.FLIGHTS) == 5
    connecting = [t for t, conns in store.CONNECTIONS.items() if conns]
    assert len(connecting) == 12
    at_risk = [t for t, conns in store.CONNECTIONS.items()
               if any(c.is_at_risk for c in conns)]
    assert len(at_risk) == 10  # 7 (AA401) + 3 (AA402)
    safe = [t for t, conns in store.CONNECTIONS.items()
            if conns and not any(c.is_at_risk for c in conns)]
    assert len(safe) == 2   # BA-011, BA-012
