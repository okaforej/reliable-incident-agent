"""Incident replay repository backed by SQLite and SQLAlchemy Core."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .db import get_engine
from .models import (
    BehavioralEvaluation,
    ExpectedOutcome,
    InvestigationTrace,
    ScenarioDetail,
    ScenarioEvidence,
    ScenarioSummary,
    ToolCall,
)


def _loads(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


class ReplayRepository:
    """Query boundary between observability tools and the incident replay DB."""

    def __init__(self, engine: Engine | None = None):
        self.engine = engine or get_engine()

    def list_scenarios(self) -> list[ScenarioSummary]:
        query = text(
            """
            SELECT
              scenarios.id,
              scenarios.name,
              scenarios.description,
              incidents.id AS incident_id,
              incidents.severity,
              incidents.affected_service
            FROM scenarios
            JOIN incidents ON incidents.scenario_id = scenarios.id
            ORDER BY scenarios.id
            """
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query).mappings().all()
        return [ScenarioSummary(**dict(row)) for row in rows]

    def get_scenario(self, scenario_id: str) -> ScenarioDetail:
        scenario = self._one(
            "SELECT id, name, description FROM scenarios WHERE id = :scenario_id",
            scenario_id=scenario_id,
        )
        incident = self.get_incident(scenario_id)
        services = self._all(
            "SELECT id, name, kind, team FROM services WHERE scenario_id = :scenario_id ORDER BY name",
            scenario_id=scenario_id,
        )
        dependencies = self.get_dependencies(scenario_id)
        changes = self.get_recent_changes(scenario_id)
        return ScenarioDetail(
            id=scenario["id"],
            name=scenario["name"],
            description=scenario["description"],
            incident=incident,
            services=services,
            dependencies=dependencies,
            changes=changes,
        )

    def get_incident(self, scenario_id: str) -> dict[str, Any]:
        row = self._one(
            """
            SELECT id, title, severity, started_at, ended_at, affected_service,
                   customer_impact, symptoms_json
            FROM incidents
            WHERE scenario_id = :scenario_id
            """,
            scenario_id=scenario_id,
        )
        row["symptoms"] = _loads(row.pop("symptoms_json"), [])
        return row

    def get_expected_outcome(self, scenario_id: str) -> ExpectedOutcome:
        row = self._one(
            "SELECT root_cause FROM expected_outcomes WHERE scenario_id = :scenario_id",
            scenario_id=scenario_id,
        )
        return ExpectedOutcome(root_cause=row["root_cause"])

    def get_dependencies(self, scenario_id: str, service: str | None = None) -> list[dict[str, Any]]:
        where = "scenario_id = :scenario_id"
        params: dict[str, Any] = {"scenario_id": scenario_id}
        if service:
            where += " AND source_service = :service"
            params["service"] = service
        rows = self._all(
            f"""
            SELECT id, source_service, target_service, protocol, critical_paths_json
            FROM dependencies
            WHERE {where}
            ORDER BY source_service, target_service
            """,
            **params,
        )
        for row in rows:
            row["critical_paths"] = _loads(row.pop("critical_paths_json"), [])
        return rows

    def get_metrics(
        self,
        scenario_id: str,
        service: str,
        metric_name: str | None = None,
    ) -> list[dict[str, Any]]:
        where = "metrics.scenario_id = :scenario_id AND metrics.service = :service"
        params: dict[str, Any] = {"scenario_id": scenario_id, "service": service}
        if metric_name:
            where += " AND metrics.name = :metric_name"
            params["metric_name"] = metric_name
        metric_rows = self._all(
            f"""
            SELECT id, service, name, unit, description, threshold
            FROM metrics
            WHERE {where}
            ORDER BY id
            """,
            **params,
        )
        for metric in metric_rows:
            metric["points"] = self._all(
                """
                SELECT ts, value
                FROM metric_points
                WHERE metric_id = :metric_id
                ORDER BY ts
                """,
                metric_id=metric["id"],
            )
        return metric_rows

    def search_logs(
        self,
        scenario_id: str,
        service: str,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        where = "scenario_id = :scenario_id AND service = :service"
        params: dict[str, Any] = {"scenario_id": scenario_id, "service": service}
        if query:
            where += " AND lower(message || ' ' || fields_json) LIKE :query"
            params["query"] = f"%{query.lower()}%"
        rows = self._all(
            f"""
            SELECT id, ts, service, level, message, fields_json
            FROM logs
            WHERE {where}
            ORDER BY ts
            """,
            **params,
        )
        for row in rows:
            row["fields"] = _loads(row.pop("fields_json"), {})
        return rows

    def get_recent_changes(self, scenario_id: str, service: str | None = None) -> list[dict[str, Any]]:
        where = "scenario_id = :scenario_id"
        params: dict[str, Any] = {"scenario_id": scenario_id}
        if service:
            where += " AND service = :service"
            params["service"] = service
        rows = self._all(
            f"""
            SELECT id, ts, service, kind, summary, details_json
            FROM changes
            WHERE {where}
            ORDER BY ts
            """,
            **params,
        )
        for row in rows:
            row["details"] = _loads(row.pop("details_json"), {})
        return rows

    def get_service_health(self, scenario_id: str, service: str) -> dict[str, Any]:
        metrics = self.get_metrics(scenario_id, service)
        logs = self.search_logs(scenario_id, service)
        status = "healthy"
        signals: list[str] = []
        for metric in metrics:
            values = [point["value"] for point in metric["points"]]
            threshold = metric["threshold"]
            if threshold is not None and values and max(values) >= threshold:
                status = "critical"
                signals.append(f"{metric['name']} reached {max(values):g} {metric['unit']}")
        error_count = sum(1 for log in logs if log["level"] in {"error", "warn"})
        if error_count:
            status = "critical" if status == "critical" else "degraded"
            signals.append(f"{error_count} warning/error log events")
        return {
            "service": service,
            "status": status,
            "signals": signals,
            "metrics": metrics,
            "log_count": len(logs),
        }

    def get_evidence(self, scenario_id: str) -> ScenarioEvidence:
        metrics = self._all(
            """
            SELECT id, service, name, unit, description, threshold
            FROM metrics
            WHERE scenario_id = :scenario_id
            ORDER BY service, name
            """,
            scenario_id=scenario_id,
        )
        for metric in metrics:
            metric["points"] = self._all(
                "SELECT ts, value FROM metric_points WHERE metric_id = :metric_id ORDER BY ts",
                metric_id=metric["id"],
            )
        return ScenarioEvidence(
            scenario_id=scenario_id,
            metrics=metrics,
            logs=self.search_all_logs(scenario_id),
            changes=self.get_recent_changes(scenario_id),
            dependencies=self.get_dependencies(scenario_id),
        )

    def search_all_logs(self, scenario_id: str) -> list[dict[str, Any]]:
        rows = self._all(
            """
            SELECT id, ts, service, level, message, fields_json
            FROM logs
            WHERE scenario_id = :scenario_id
            ORDER BY ts
            """,
            scenario_id=scenario_id,
        )
        for row in rows:
            row["fields"] = _loads(row.pop("fields_json"), {})
        return rows

    def persist_run(
        self,
        scenario_id: str,
        mode: str,
        trace: InvestigationTrace,
        evaluation: BehavioralEvaluation,
    ) -> str:
        run_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO investigation_runs
                    (id, scenario_id, mode, created_at, incident_id, incident_description, final_root_cause)
                    VALUES (:id, :scenario_id, :mode, :created_at, :incident_id, :incident_description, :final_root_cause)
                    """
                ),
                {
                    "id": run_id,
                    "scenario_id": scenario_id,
                    "mode": mode,
                    "created_at": created_at,
                    "incident_id": trace.incident_id,
                    "incident_description": trace.incident_description,
                    "final_root_cause": trace.final_root_cause,
                },
            )
            for call in trace.tool_calls:
                conn.execute(
                    text(
                        """
                        INSERT INTO tool_calls (run_id, sequence, tool_name, arguments_json, result_json)
                        VALUES (:run_id, :sequence, :tool_name, :arguments_json, :result_json)
                        """
                    ),
                    {
                        "run_id": run_id,
                        "sequence": call.sequence,
                        "tool_name": call.tool_name,
                        "arguments_json": json.dumps(call.arguments),
                        "result_json": json.dumps(call.result),
                    },
                )
            conn.execute(
                text(
                    """
                    INSERT INTO evaluations
                    (run_id, rca_correct, grounded, investigation_sufficient, tool_efficient, behavioral_slo_pass, reasons_json)
                    VALUES (:run_id, :rca_correct, :grounded, :investigation_sufficient, :tool_efficient, :behavioral_slo_pass, :reasons_json)
                    """
                ),
                {
                    "run_id": run_id,
                    "rca_correct": int(evaluation.rca_correct),
                    "grounded": int(evaluation.grounded),
                    "investigation_sufficient": int(evaluation.investigation_sufficient),
                    "tool_efficient": int(evaluation.tool_efficient),
                    "behavioral_slo_pass": int(evaluation.behavioral_slo_pass),
                    "reasons_json": json.dumps(evaluation.reasons),
                },
            )
        return run_id

    def get_run(self, run_id: str) -> InvestigationTrace:
        run = self._one(
            """
            SELECT incident_id, incident_description, final_root_cause
            FROM investigation_runs
            WHERE id = :run_id
            """,
            run_id=run_id,
        )
        calls = self._all(
            """
            SELECT sequence, tool_name, arguments_json, result_json
            FROM tool_calls
            WHERE run_id = :run_id
            ORDER BY sequence
            """,
            run_id=run_id,
        )
        tool_calls = [
            ToolCall(
                sequence=row["sequence"],
                tool_name=row["tool_name"],
                arguments=_loads(row["arguments_json"], {}),
                result=_loads(row["result_json"], {}),
            )
            for row in calls
        ]
        return InvestigationTrace(
            incident_id=run["incident_id"],
            incident_description=run["incident_description"],
            tool_calls=tool_calls,
            final_root_cause=run["final_root_cause"],
        )

    def get_evaluation(self, run_id: str) -> BehavioralEvaluation:
        row = self._one(
            """
            SELECT rca_correct, grounded, investigation_sufficient, tool_efficient,
                   behavioral_slo_pass, reasons_json
            FROM evaluations
            WHERE run_id = :run_id
            """,
            run_id=run_id,
        )
        return BehavioralEvaluation(
            rca_correct=bool(row["rca_correct"]),
            grounded=bool(row["grounded"]),
            investigation_sufficient=bool(row["investigation_sufficient"]),
            tool_efficient=bool(row["tool_efficient"]),
            behavioral_slo_pass=bool(row["behavioral_slo_pass"]),
            reasons=_loads(row["reasons_json"], []),
        )

    def _one(self, sql: str, **params: Any) -> dict[str, Any]:
        rows = self._all(sql, **params)
        if not rows:
            raise KeyError(f"No row for query: {sql.strip()} params={params}")
        return rows[0]

    def _all(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text(sql), params).mappings().all()]
