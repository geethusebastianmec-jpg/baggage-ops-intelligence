"""Base class for all mock tool wrappers."""
import random
import time
from datetime import datetime, timezone
from typing import Any

from src.config import settings
from src.models import ActionRecord


class BaseTool:
    name: str = "base_tool"

    def _latency(self) -> None:
        if settings.tool_latency_ms > 0:
            time.sleep(settings.tool_latency_ms / 1000)

    def _should_fail(self) -> bool:
        return settings.inject_tool_failures and random.random() < 0.1

    def _record(
        self,
        decision_id: str,
        disruption_id: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        success: bool,
        duration_ms: int,
        error: str | None = None,
    ) -> ActionRecord:
        return ActionRecord(
            decision_id=decision_id,
            disruption_id=disruption_id,
            agent="tier3",
            tool=self.name,
            input=input_data,
            output=output_data,
            success=success,
            error=error,
            duration_ms=duration_ms,
        )
