"""Observability tool interface used by the investigator runtime."""

from __future__ import annotations

from typing import Any

from .models import ToolCall
from .replay import ReplayRepository


class ObservabilityTools:
    def __init__(self, scenario_id: str, repository: ReplayRepository | None = None):
        self.scenario_id = scenario_id
        self.repository = repository or ReplayRepository()
        self.calls: list[ToolCall] = []

    def get_service_health(self, service: str) -> dict[str, Any]:
        return self._record(
            "get_service_health",
            {"service": service},
            self.repository.get_service_health(self.scenario_id, service),
        )

    def search_logs(self, service: str, query: str | None = None) -> dict[str, Any]:
        return self._record(
            "search_logs",
            {"service": service, "query": query},
            {
                "service": service,
                "query": query,
                "matches": self.repository.search_logs(self.scenario_id, service, query),
            },
        )

    def get_metrics(self, service: str, metric_name: str | None = None) -> dict[str, Any]:
        return self._record(
            "get_metrics",
            {"service": service, "metric_name": metric_name},
            {
                "service": service,
                "metric_name": metric_name,
                "metrics": self.repository.get_metrics(self.scenario_id, service, metric_name),
            },
        )

    def get_recent_changes(self, service: str) -> dict[str, Any]:
        return self._record(
            "get_recent_changes",
            {"service": service},
            {"service": service, "changes": self.repository.get_recent_changes(self.scenario_id, service)},
        )

    def get_dependencies(self, service: str) -> dict[str, Any]:
        return self._record(
            "get_dependencies",
            {"service": service},
            {"service": service, "dependencies": self.repository.get_dependencies(self.scenario_id, service)},
        )

    def _record(self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(
            ToolCall(
                sequence=len(self.calls) + 1,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
            )
        )
        return result
