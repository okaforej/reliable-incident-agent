"""Deterministic investigator runtime for replay comparisons."""

from __future__ import annotations

from typing import Literal

from .models import InvestigationTrace
from .replay import ReplayRepository
from .tools import ObservabilityTools

FINAL_RCA = (
    "Checkout latency was caused by postgres connection exhaustion after checkout "
    "deployed a database pool max_open_connections change from 20 to 80."
)
PAYMENTS_RCA = (
    "Checkout payment failures were caused by payments gateway timeouts after "
    "payments lowered the external card gateway timeout to 500 ms."
)
INCONCLUSIVE_RCA = (
    "Insufficient evidence to determine a single root cause for the frontend "
    "product page errors."
)


def _incident_description(incident: dict[str, object]) -> str:
    symptoms = "; ".join(str(item) for item in incident.get("symptoms", []))
    return (
        f"{incident['title']}. Impact: {incident['customer_impact']} "
        f"Symptoms: {symptoms}"
    )


def run_investigation(
    scenario_id: str,
    mode: Literal["baseline", "candidate"],
    repository: ReplayRepository | None = None,
) -> InvestigationTrace:
    repo = repository or ReplayRepository()
    incident = repo.get_incident(scenario_id)
    tools = ObservabilityTools(scenario_id, repo)

    if scenario_id == "payments_gateway_timeout":
        return _run_payments_gateway(incident, tools)

    if scenario_id == "insufficient_frontend_evidence":
        return _run_insufficient_frontend(incident, tools)

    if mode == "candidate":
        tools.search_logs("checkout", query="timeout")
        return InvestigationTrace(
            incident_id=str(incident["id"]),
            incident_description=_incident_description(incident),
            tool_calls=tools.calls,
            final_root_cause=FINAL_RCA,
        )

    tools.get_service_health("checkout")
    tools.search_logs("checkout", query=None)
    tools.get_dependencies("checkout")
    tools.get_metrics("postgres", metric_name="db.connections.active")
    tools.get_service_health("postgres")
    tools.get_recent_changes("checkout")
    tools.search_logs("payments", query="cancelled")

    return InvestigationTrace(
        incident_id=str(incident["id"]),
        incident_description=_incident_description(incident),
        tool_calls=tools.calls,
        final_root_cause=FINAL_RCA,
    )


def _run_payments_gateway(
    incident: dict[str, object],
    tools: ObservabilityTools,
) -> InvestigationTrace:
    tools.get_service_health("checkout")
    tools.search_logs("checkout", query="payment")
    tools.get_dependencies("checkout")
    tools.get_service_health("payments")
    tools.get_metrics("payments", metric_name="gateway.timeout.rate_per_min")
    tools.search_logs("payments", query="gateway")
    tools.get_service_health("postgres")
    tools.get_recent_changes("payments")
    return InvestigationTrace(
        incident_id=str(incident["id"]),
        incident_description=_incident_description(incident),
        tool_calls=tools.calls,
        final_root_cause=PAYMENTS_RCA,
    )


def _run_insufficient_frontend(
    incident: dict[str, object],
    tools: ObservabilityTools,
) -> InvestigationTrace:
    tools.get_service_health("frontend")
    tools.search_logs("frontend", query=None)
    tools.get_dependencies("frontend")
    tools.get_service_health("checkout")
    tools.get_recent_changes("frontend")
    return InvestigationTrace(
        incident_id=str(incident["id"]),
        incident_description=_incident_description(incident),
        tool_calls=tools.calls,
        final_root_cause=INCONCLUSIVE_RCA,
    )
