from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    google_api_key: str = ""

    # ── Kafka ────────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:19092"
    # SASL settings for Upstash Kafka (leave blank for local Redpanda)
    kafka_security_protocol: str = "PLAINTEXT"     # SASL_SSL for Upstash
    kafka_sasl_mechanism: str = ""                  # SCRAM-SHA-256 for Upstash
    kafka_sasl_username: str = ""
    kafka_sasl_password: str = ""

    # ── Persistence ──────────────────────────────────────────────────────────
    postgres_dsn: str = "postgresql://baggage:baggage@localhost:5432/baggage_ops"
    redis_url: str = "redis://localhost:6379/0"

    # ── LangSmith ────────────────────────────────────────────────────────────
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "baggage-demo"

    # ── Model selection ──────────────────────────────────────────────────────
    llm_tier1_novel: str = "gemini-1.5-pro"
    llm_tier1_playbook: str = "gemini-2.0-flash"
    llm_tier2: str = "gemini-2.0-flash"

    # ── Service URLs (set in cloud env) ──────────────────────────────────────
    # Dashboard uses this to reach the API service
    api_url: str = "http://localhost:8000"

    # ── Demo ─────────────────────────────────────────────────────────────────
    demo_airport: str = "JFK"
    tool_latency_ms: int = 100
    inject_tool_failures: bool = False


settings = Settings()
