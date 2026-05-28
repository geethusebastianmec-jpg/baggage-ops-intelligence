"""Kafka topic name constants — single source of truth."""


class Topics:
    FLIGHT_DELAYS = "ops.flights.delays"
    GATE_CHANGES = "ops.flights.gate-changes"
    CANCELLATIONS = "ops.flights.cancellations"
    BAGGAGE_EXCEPTIONS = "ops.baggage.exceptions"
    RAMP_CREW_STATUS = "ops.ramp.crew-status"
    EQUIPMENT_ALERTS = "ops.equipment.alerts"
    DECISIONS_CONFLICTS = "ops.decisions.conflicts"
    DECISIONS_RESOLVED = "ops.decisions.resolved"
    DECISIONS_PLAYBOOKS = "ops.decisions.playbooks"
    AUDIT_ACTIONS = "ops.audit.actions"


# Maps each topic to the coordinator(s) that consume it
TOPIC_COORDINATOR_MAP: dict[str, list[str]] = {
    Topics.FLIGHT_DELAYS: ["baggage_coordinator", "ramp_coordinator"],
    Topics.GATE_CHANGES: ["ramp_coordinator", "comms_coordinator"],
    Topics.CANCELLATIONS: ["baggage_coordinator", "dispatch_coordinator", "comms_coordinator"],
    Topics.BAGGAGE_EXCEPTIONS: ["dispatch_coordinator", "comms_coordinator"],
    Topics.RAMP_CREW_STATUS: ["baggage_coordinator"],
    Topics.DECISIONS_CONFLICTS: ["supervisor"],
}
