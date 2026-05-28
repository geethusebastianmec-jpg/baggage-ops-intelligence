"""Ramp operations (ground crew + equipment) mock tool."""
from src.models import CrewStatus, TaskTicket
from src.tools import store
from src.tools.base import BaseTool


class RampTool(BaseTool):
    name = "ramp"

    def get_crew_availability(self, zone: str) -> CrewStatus | None:
        self._latency()
        return store.CREW_STATUS.get(zone)

    def assign_exception_task(
        self,
        bag_tags: list[str],
        from_flight: str,
        to_flight: str,
        zone: str,
    ) -> TaskTicket | None:
        self._latency()
        if self._should_fail():
            raise RuntimeError("Ramp dispatch system unavailable")

        crew = store.CREW_STATUS.get(zone)
        if not crew or not crew.can_take_exception:
            return None

        # Update crew status — one more active task
        store.CREW_STATUS[zone] = crew.model_copy(update={
            "active_tasks": crew.active_tasks + 1,
            "available_crew": max(0, crew.available_crew - 1),
        })

        ticket = TaskTicket(
            task_type="EXCEPTION_TRANSFER",
            bag_tags=bag_tags,
            from_flight=from_flight,
            to_flight=to_flight,
            assigned_zone=zone,
        )
        store.ACTION_LOG.append({
            "tool": self.name,
            "action": "assign_exception_task",
            "ticket_id": ticket.ticket_id,
            "bag_tags": bag_tags,
            "from_flight": from_flight,
            "to_flight": to_flight,
            "zone": zone,
        })
        return ticket

    def complete_task(self, ticket_id: str, zone: str) -> bool:
        """Mark a task complete, freeing crew capacity."""
        self._latency()
        crew = store.CREW_STATUS.get(zone)
        if not crew:
            return False
        store.CREW_STATUS[zone] = crew.model_copy(update={
            "active_tasks": max(0, crew.active_tasks - 1),
            "available_crew": min(crew.total_crew, crew.available_crew + 1),
        })
        return True
