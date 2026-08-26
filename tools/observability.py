"""Structured local observability tools backed by tiny JSON fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _read_json(name: str, default: Any) -> Any:
    path = DATA_DIR / name
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_incidents() -> list[dict[str, Any]]:
    data = _read_json("incidents.json", {"incidents": []})
    if isinstance(data, dict):
        return data.get("incidents", [])
    return data


class ObservabilityTools:
    """Small tool surface intentionally similar to incident-response workflows."""

    def __init__(self, incident_id: str):
        self.incident_id = incident_id
        self._health = _read_json("service_health.json", {"snapshots": []}).get("snapshots", [])
        self._metrics = _read_json("metrics.json", {"metrics": []}).get("metrics", [])
        self._logs = _read_json("logs.json", {"logs": []}).get("logs", [])
        self._changes = _read_json("changes.json", {"changes": []}).get("changes", [])
        self._dependencies = _read_json("dependencies.json", {"services": []}).get("services", [])

    def get_service_health(self, service: str) -> dict[str, Any]:
        snapshot = next(
            (
                item
                for item in self._health
                if item.get("incident_id") == self.incident_id
            ),
            None,
        )
        result = None
        if snapshot:
            result = next(
                (
                    item
                    for item in snapshot.get("services", [])
                    if item.get("name") == service
                ),
                None,
            )
        if result is None:
            return {
                "service": service,
                "status": "unknown",
                "summary": "No health data available for this service in the incident window.",
                "signals": [],
            }
        return {"service": service, **result}

    def search_logs(self, service: str, query: str | None = None) -> dict[str, Any]:
        query_text = (query or "").lower()
        matches = []
        for entry in self._logs:
            if entry.get("incident_id") != self.incident_id:
                continue
            if entry.get("service") != service:
                continue
            haystack = " ".join(
                str(entry.get(field, ""))
                for field in ("message", "level", "component", "evidence_tag")
            ).lower()
            if query_text and query_text not in haystack:
                continue
            matches.append(entry)
        return {
            "service": service,
            "query": query,
            "matches": matches,
            "count": len(matches),
        }

    def get_recent_changes(self, service: str) -> dict[str, Any]:
        changes = [
            change
            for change in self._changes
            if change.get("service") == service
            and (
                change.get("incident_id") == self.incident_id
                or "incident_id" not in change
            )
        ]
        return {"service": service, "changes": changes, "count": len(changes)}

    def get_metrics(self, service: str) -> dict[str, Any]:
        metrics = [
            metric
            for metric in self._metrics
            if metric.get("incident_id") == self.incident_id
            and metric.get("service") == service
        ]
        return {"service": service, "metrics": metrics, "count": len(metrics)}

    def get_dependencies(self, service: str) -> dict[str, Any]:
        service_record = next(
            (item for item in self._dependencies if item.get("name") == service),
            {},
        )
        dependencies = service_record.get("calls", [])
        return {"service": service, "dependencies": dependencies}

    def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "get_service_health":
            return self.get_service_health(arguments["service"])
        if tool_name == "search_logs":
            return self.search_logs(arguments["service"], arguments.get("query"))
        if tool_name == "get_recent_changes":
            return self.get_recent_changes(arguments["service"])
        if tool_name == "get_dependencies":
            return self.get_dependencies(arguments["service"])
        if tool_name == "get_metrics":
            return self.get_metrics(arguments["service"])
        raise ValueError(f"Unknown observability tool: {tool_name}")
