"""Builds confluent-kafka config dicts for both local Redpanda (PLAINTEXT)
and Redpanda Cloud / Upstash (SASL_SSL). One function call, zero duplication.
"""
from src.config import settings


def _base() -> dict:
    cfg = {"bootstrap.servers": settings.kafka_bootstrap_servers}
    if settings.kafka_security_protocol != "PLAINTEXT" and settings.kafka_sasl_username:
        cfg.update({
            "security.protocol": settings.kafka_security_protocol,
            "sasl.mechanism": settings.kafka_sasl_mechanism,
            "sasl.username": settings.kafka_sasl_username,
            "sasl.password": settings.kafka_sasl_password,
        })
    return cfg


def producer_config(extra: dict | None = None) -> dict:
    cfg = _base()
    if extra:
        cfg.update(extra)
    return cfg


def consumer_config(group_id: str, auto_offset_reset: str = "latest", extra: dict | None = None) -> dict:
    cfg = {**_base(), "group.id": group_id,
           "auto.offset.reset": auto_offset_reset, "enable.auto.commit": True}
    if extra:
        cfg.update(extra)
    return cfg
