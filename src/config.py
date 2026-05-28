from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    google_api_key: str = ""
    kafka_bootstrap_servers: str = "localhost:19092"
    postgres_dsn: str = "postgresql://baggage:baggage@localhost:5432/baggage_ops"
    redis_url: str = "redis://localhost:6379/0"

    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "baggage-demo"

    # Tier 1 novel: most capable Gemini model for compound disruption reasoning
    llm_tier1_novel: str = "gemini-1.5-pro"
    # Tier 1 playbook + Tier 2: fast Flash model for classification and DAG planning
    llm_tier1_playbook: str = "gemini-2.0-flash"
    llm_tier2: str = "gemini-2.0-flash"

    demo_airport: str = "JFK"
    tool_latency_ms: int = 150
    inject_tool_failures: bool = False


settings = Settings()
