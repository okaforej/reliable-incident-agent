"""Validated replay tools used by the LLM investigator runtime."""

from __future__ import annotations

import time
from typing import Any, Optional

from .models import ToolCall
from .replay import ReplayRepository

TOOL_SCHEMA_VERSION = "observability-v2"


READ_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_service_health",
        "description": (
            "Broadly triage whether one service is healthy, degraded, or critical, "
            "including representative metric evidence. Use targeted metric or log "
            "queries only when a remaining question needs deeper evidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "purpose": {"type": "string"},
            },
            "required": ["service", "purpose"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "search_logs",
        "description": "Retrieve structured logs for one service, optionally filtered by a query string.",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "query": {"type": ["string", "null"]},
                "purpose": {"type": "string"},
            },
            "required": ["service", "query", "purpose"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_metrics",
        "description": (
            "Retrieve detailed time-series metrics for one service, optionally filtered "
            "by metric name. Prefer a targeted metric when service health already supplied "
            "a broad summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "metric_name": {"type": ["string", "null"]},
                "purpose": {"type": "string"},
            },
            "required": ["service", "metric_name", "purpose"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_dependencies",
        "description": "Retrieve direct dependencies for one service.",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "purpose": {"type": "string"},
            },
            "required": ["service", "purpose"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_recent_changes",
        "description": "Retrieve recent deployment or configuration changes for one service.",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "purpose": {"type": "string"},
            },
            "required": ["service", "purpose"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


class ObservabilityTools:
    def __init__(
        self,
        scenario_id: str,
        repository: Optional[ReplayRepository] = None,
        replay_instance_id: Optional[str] = None,
    ):
        self.scenario_id = scenario_id
        self.repository = repository or ReplayRepository()
        self.replay_instance_id = replay_instance_id
        self.calls: list[ToolCall] = []

    def execute(self, tool_name: str, arguments: dict[str, Any], purpose: str = "") -> ToolCall:
        started = time.perf_counter()
        args = dict(arguments)
        args.pop("purpose", None)
        try:
            _validate_arguments(tool_name, args)
            result = self._execute_result(tool_name, args)
            status = "ok"
        except KeyError:
            result = {
                "error": "Requested observability data was not found.",
                "tool_name": tool_name,
            }
            status = "error"
        except (TypeError, ValueError) as exc:
            result = {"error": str(exc), "tool_name": tool_name}
            status = "error"
        duration_ms = int((time.perf_counter() - started) * 1000)
        call = ToolCall(
            sequence=len(self.calls) + 1,
            tool_name=tool_name,
            purpose=purpose or str(arguments.get("purpose") or ""),
            arguments=args,
            result=result,
            evidence_ids=_collect_evidence_ids(result),
            status=status,
            duration_ms=duration_ms,
        )
        self.calls.append(call)
        return call

    def _execute_result(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        service = _string_argument(arguments, "service")
        if tool_name == "get_service_health":
            return self.repository.get_service_health(
                self.scenario_id,
                service,
                replay_instance_id=self.replay_instance_id,
            )
        if tool_name == "search_logs":
            query = arguments.get("query")
            matches = self.repository.search_logs(
                self.scenario_id,
                service,
                query if isinstance(query, str) else None,
                replay_instance_id=self.replay_instance_id,
            )
            return {
                "service": service,
                "query": query,
                "matches": matches,
                **_negative_evidence(tool_name, service, "logs", matches),
            }
        if tool_name == "get_metrics":
            metric_name = arguments.get("metric_name")
            metrics = self.repository.get_metrics(
                self.scenario_id,
                service,
                metric_name if isinstance(metric_name, str) else None,
                replay_instance_id=self.replay_instance_id,
            )
            return {
                "service": service,
                "metric_name": metric_name,
                "metrics": metrics,
                **_negative_evidence(tool_name, service, "metrics", metrics),
            }
        if tool_name == "get_dependencies":
            dependencies = self.repository.get_dependencies(self.scenario_id, service)
            return {
                "service": service,
                "dependencies": dependencies,
                **_negative_evidence(tool_name, service, "dependencies", dependencies),
            }
        if tool_name == "get_recent_changes":
            changes = self.repository.get_recent_changes(
                self.scenario_id,
                service,
                replay_instance_id=self.replay_instance_id,
            )
            return {
                "service": service,
                "changes": changes,
                **_negative_evidence(tool_name, service, "changes", changes),
            }
        raise ValueError(f"Unknown tool: {tool_name}")


def _string_argument(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Tool argument {key!r} must be a non-empty string.")
    return value


def _validate_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    if tool_name in {"get_service_health", "get_dependencies", "get_recent_changes"}:
        allowed = {"service"}
    elif tool_name == "search_logs":
        allowed = {"service", "query"}
    elif tool_name == "get_metrics":
        allowed = {"service", "metric_name"}
    else:
        raise ValueError(f"Unknown tool: {tool_name}")
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise ValueError(f"Unexpected arguments for {tool_name}: {', '.join(extra)}")
    _string_argument(arguments, "service")
    if "query" in arguments and arguments["query"] is not None and not isinstance(arguments["query"], str):
        raise TypeError("Tool argument 'query' must be a string or null.")
    if (
        "metric_name" in arguments
        and arguments["metric_name"] is not None
        and not isinstance(arguments["metric_name"], str)
    ):
        raise TypeError("Tool argument 'metric_name' must be a string or null.")


def _negative_evidence(tool_name: str, service: str, family: str, values: list[Any]) -> dict[str, str]:
    if values:
        return {}
    return {
        "evidence_id": f"neg_{_safe_token(service)}_{_safe_token(tool_name)}_{family}_none",
        "observation": f"No {family} were returned for service {service}.",
    }


def _safe_token(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.lower()).strip("_")


def _collect_evidence_ids(value: Any) -> list[str]:
    found: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"id", "evidence_id"} and isinstance(child, str):
                    found.append(child)
                else:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return sorted(set(found))
