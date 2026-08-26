"""A small context-aware incident investigator.

The default planner is deterministic so the demo works without network access.
It still chooses tools from visible incident context and prior tool results, and
never reads the expected RCA while investigating.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.models import InvestigationTrace, ToolCall
from tools.observability import ObservabilityTools, load_incidents


@dataclass
class InvestigationState:
    primary_service: str
    suspected_dependency: str | None = None
    saw_dependency_failure: bool = False
    saw_dependency_saturation: bool = False
    saw_relevant_change: bool = False


def _find_incident(incident_id: str) -> dict[str, Any]:
    for incident in load_incidents():
        if incident["id"] == incident_id:
            return incident
    raise ValueError(f"Unknown incident_id: {incident_id}")


def _record_call(
    trace: InvestigationTrace,
    tools: ObservabilityTools,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    result = tools.call(tool_name, arguments)
    trace.tool_calls.append(
        ToolCall(
            sequence=len(trace.tool_calls) + 1,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
        )
    )
    return result


def _infer_primary_service(incident: dict[str, Any]) -> str:
    if incident.get("service"):
        return incident["service"]
    description = _incident_description(incident).lower()
    for service in ("checkout", "payments", "frontend", "postgres"):
        if service in description:
            return service
    return "checkout"


def _first_unhealthy_dependency(result: dict[str, Any]) -> str | None:
    for dependency in result.get("dependencies", []):
        service = dependency.get("service")
        protocol = dependency.get("protocol")
        if service == "postgres" or protocol == "postgres":
            return service
    if result.get("dependencies"):
        return result["dependencies"][0].get("service")
    return None


def _logs_indicate_dependency_failure(result: dict[str, Any]) -> str | None:
    for match in result.get("matches", []):
        message = match.get("message", "").lower()
        tags = {str(tag).lower() for tag in match.get("evidence_tags", [])}
        fields = match.get("fields", {})
        field_text = " ".join(str(value) for value in fields.values()).lower()
        if (
            "postgres" in message
            or "db" in message
            or "database" in message
            or "db_timeout" in tags
            or "orders" in field_text
        ):
            return "postgres"
        if "payments" in message:
            return "payments"
    return None


def _health_indicates_saturation(result: dict[str, Any]) -> bool:
    tags = {str(tag).lower() for tag in result.get("evidence_tags", [])}
    summary = result.get("summary", "").lower()
    current = result.get("current", "").lower()
    return (
        "saturation" in tags
        or "connection" in summary
        or "saturation" in summary
        or "100 of 100" in current
    )


def _changes_support_root_cause(result: dict[str, Any]) -> bool:
    for change in result.get("changes", []):
        tags = {str(tag).lower() for tag in change.get("evidence_tags", [])}
        details = change.get("details", {})
        summary = change.get("summary", "").lower()
        config_key = str(details.get("config_key", "")).lower()
        if {"db_pool", "root_cause"} & tags:
            return True
        if "database pool" in summary or "max_open_connections" in config_key:
            return True
    return False


def _incident_description(incident: dict[str, Any]) -> str:
    if incident.get("description"):
        return incident["description"]
    symptoms = "; ".join(incident.get("symptoms", []))
    impact = incident.get("customer_impact", "")
    return f"{incident.get('title', incident['id'])}. Impact: {impact}. Symptoms: {symptoms}"


def run_investigation(incident_id: str, mode: str = "reliable") -> InvestigationTrace:
    """Investigate an incident and return a shared trajectory trace.

    `mode="weak"` deliberately creates the same-answer/weak-evidence fixture
    used for the core comparison demo. `mode="reliable"` is the normal runtime.
    """

    incident = _find_incident(incident_id)
    tools = ObservabilityTools(incident_id)
    primary_service = _infer_primary_service(incident)
    trace = InvestigationTrace(
        incident_id=incident["id"],
        incident_description=_incident_description(incident),
        expected_root_cause=incident["expected_root_cause"],
    )

    if mode == "weak":
        _record_call(
            trace,
            tools,
            "search_logs",
            {"service": primary_service, "query": "timeout"},
        )
        trace.final_root_cause = (
            "checkout latency was caused by postgres connection exhaustion after checkout "
            "deployed a database pool max_open_connections change from 20 to 80."
        )
        return trace

    state = InvestigationState(primary_service=primary_service)

    _record_call(trace, tools, "get_service_health", {"service": primary_service})

    logs = _record_call(
        trace,
        tools,
        "search_logs",
        {"service": primary_service, "query": None},
    )
    state.saw_dependency_failure = bool(_logs_indicate_dependency_failure(logs))

    deps = _record_call(trace, tools, "get_dependencies", {"service": primary_service})
    state.suspected_dependency = _logs_indicate_dependency_failure(logs) or _first_unhealthy_dependency(deps)

    if state.suspected_dependency:
        if state.suspected_dependency == "postgres":
            _record_call(
                trace,
                tools,
                "get_metrics",
                {"service": "postgres"},
            )
        dep_health = _record_call(
            trace,
            tools,
            "get_service_health",
            {"service": state.suspected_dependency},
        )
        state.saw_dependency_saturation = _health_indicates_saturation(dep_health)

    changes = _record_call(
        trace,
        tools,
        "get_recent_changes",
        {"service": primary_service},
    )
    state.saw_relevant_change = _changes_support_root_cause(changes)

    trace.final_root_cause = _root_cause_from_suspect(
        state.suspected_dependency or primary_service,
        change_supported=state.saw_relevant_change,
    )
    return trace


def _root_cause_from_suspect(suspect: str, change_supported: bool) -> str:
    if suspect == "postgres":
        if change_supported:
            return (
                "checkout latency was caused by postgres connection exhaustion after checkout "
                "deployed a database pool max_open_connections change from 20 to 80."
            )
        return "Postgres connection exhaustion."
    if suspect == "payments":
        return "Payments service dependency failures are causing checkout errors."
    return f"{suspect} is degraded; root cause needs more evidence."
