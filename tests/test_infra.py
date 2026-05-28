"""Phase 1 acceptance tests — verifies imports and config load correctly."""

def test_imports():
    import langgraph
    import confluent_kafka
    import redis
    import fastapi
    import pydantic
    import streamlit


def test_config_loads():
    from src.config import settings
    assert settings.kafka_bootstrap_servers
    assert settings.postgres_dsn
    assert settings.redis_url
    assert settings.llm_tier2 == "claude-sonnet-4-5"


def test_settings_have_defaults():
    from src.config import settings
    assert settings.tool_latency_ms == 150
    assert settings.demo_airport == "JFK"
    assert settings.inject_tool_failures is False
