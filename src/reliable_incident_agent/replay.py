"""Incident replay repository backed by SQLite and SQLAlchemy Core."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .db import get_engine
from .models import (
    ActionConfirmationResponse,
    ActionProposal,
    BehavioralEvaluation,
    ChatMessageResponse,
    ComparisonResponse,
    ComparisonSummary,
    ExpectedOutcome,
    InvestigationEvent,
    InvestigationFinalResult,
    InvestigationFollowUpExchange,
    InvestigationResponse,
    InvestigationRunStatus,
    InvestigationSummary,
    InvestigationTrace,
    ProviderMetadata,
    RecoveryAssessment,
    ScenarioDetail,
    ScenarioSummary,
    ToolCall,
)

CHECKOUT_ROLLBACK_SCENARIO_ID = "checkout_db_pool_exhaustion"
CHECKOUT_ROLLBACK_ARGUMENTS = {
    "service": "checkout",
    "config_key": "db.max_open_connections",
    "from_value": 80,
    "to_value": 20,
}
CHECKOUT_ROLLBACK_EVIDENCE_ID = "chg_checkout_pool_80"
CHECKOUT_ROLLBACK_EXPECTED_IMPACT = (
    "Restore the prior checkout database pool limit and reduce database saturation."
)
PUBLIC_SCENARIO_IDS = {
    "checkout_db_pool_exhaustion": "checkout_latency_spike",
    "payments_gateway_timeout": "payment_submission_failures",
    "insufficient_frontend_evidence": "frontend_error_spike",
}
PUBLIC_SCENARIO_NAMES = {
    "checkout_db_pool_exhaustion": "Checkout Latency Spike",
    "payments_gateway_timeout": "Payment Submission Failures",
    "insufficient_frontend_evidence": "Frontend Error Spike",
}
INTERNAL_SCENARIO_IDS = {public: internal for internal, public in PUBLIC_SCENARIO_IDS.items()}


def _loads(value: Optional[str], default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _dumps(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        default=lambda item: item.model_dump(mode="json") if hasattr(item, "model_dump") else str(item),
    )


class ReplayRepository:
    """Query boundary between tools, replay state, and persistence."""

    def __init__(self, engine: Optional[Engine] = None):
        self.engine = engine or get_engine()

    def list_scenarios(self) -> list[ScenarioSummary]:
        rows = self._all(
            """
            SELECT scenarios.id, scenarios.name, incidents.id AS incident_id,
                   incidents.severity, incidents.affected_service,
                   incidents.started_at, incidents.customer_impact,
                   incidents.target_sli, incidents.symptoms_json
            FROM scenarios
            JOIN incidents ON incidents.scenario_id = scenarios.id
            ORDER BY scenarios.id
            """
        )
        summaries: list[ScenarioSummary] = []
        for row in rows:
            internal_id = row["id"]
            row["id"] = public_scenario_id(internal_id)
            row["name"] = public_scenario_name(internal_id)
            row["symptoms"] = _loads(row.pop("symptoms_json"), [])
            summaries.append(ScenarioSummary(**row))
        return summaries

    def get_scenario(self, scenario_id: str) -> ScenarioDetail:
        internal_id = internal_scenario_id(scenario_id)
        scenario = self._one(
            "SELECT id, name FROM scenarios WHERE id = :scenario_id",
            scenario_id=internal_id,
        )
        incident = self.get_agent_context(internal_id)
        services = self._all(
            """
            SELECT id, name, kind, team
            FROM services
            WHERE scenario_id = :scenario_id AND name = :affected_service
            ORDER BY name
            """,
            scenario_id=internal_id,
            affected_service=incident["affected_service"],
        )
        return ScenarioDetail(
            id=public_scenario_id(scenario["id"]),
            name=public_scenario_name(scenario["id"]),
            incident=incident,
            services=services,
        )

    def get_agent_context(self, scenario_id: str) -> dict[str, Any]:
        scenario_id = internal_scenario_id(scenario_id)
        row = self._one(
            """
            SELECT id, title, severity, started_at, affected_service,
                   customer_impact, target_sli, symptoms_json
            FROM incidents
            WHERE scenario_id = :scenario_id
            """,
            scenario_id=scenario_id,
        )
        row["symptoms"] = _loads(row.pop("symptoms_json"), [])
        row["status"] = "active"
        return row

    def get_expected_outcome(self, scenario_id: str) -> ExpectedOutcome:
        scenario_id = internal_scenario_id(scenario_id)
        row = self._one(
            "SELECT root_cause FROM expected_outcomes WHERE scenario_id = :scenario_id",
            scenario_id=scenario_id,
        )
        return ExpectedOutcome(root_cause=row["root_cause"])

    def create_replay_instance(self, scenario_id: str) -> str:
        scenario_id = internal_scenario_id(scenario_id)
        self._one("SELECT 1 FROM scenarios WHERE id = :scenario_id", scenario_id=scenario_id)
        replay_instance_id = f"replay_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        initial_pool_connections = 80 if scenario_id == CHECKOUT_ROLLBACK_SCENARIO_ID else 20
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO replay_instances
                    (id, scenario_id, status, checkout_db_pool_connections,
                     created_at, updated_at)
                    VALUES (:id, :scenario_id, 'active', :pool_connections,
                            :created_at, :updated_at)
                    """
                ),
                {
                    "id": replay_instance_id,
                    "scenario_id": scenario_id,
                    "pool_connections": initial_pool_connections,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        return replay_instance_id

    def ensure_service(self, scenario_id: str, service: str) -> None:
        self._one(
            "SELECT 1 FROM services WHERE scenario_id = :scenario_id AND name = :service",
            scenario_id=scenario_id,
            service=service,
        )

    def get_dependencies(self, scenario_id: str, service: Optional[str] = None) -> list[dict[str, Any]]:
        where = "scenario_id = :scenario_id"
        params: dict[str, Any] = {"scenario_id": scenario_id}
        if service:
            self.ensure_service(scenario_id, service)
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
        metric_name: Optional[str] = None,
        replay_instance_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        self.ensure_service(scenario_id, service)
        where = "scenario_id = :scenario_id AND service = :service"
        params: dict[str, Any] = {"scenario_id": scenario_id, "service": service}
        if metric_name:
            where += " AND name = :metric_name"
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
                  AND (:include_post_action = 1 OR ts <= :active_cutoff)
                ORDER BY ts
                """,
                metric_id=metric["id"],
                active_cutoff=self._active_cutoff(scenario_id),
                include_post_action=int(
                    self._post_action_visible(scenario_id, replay_instance_id)
                ),
            )
        return metric_rows

    def search_logs(
        self,
        scenario_id: str,
        service: str,
        query: Optional[str] = None,
        replay_instance_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        self.ensure_service(scenario_id, service)
        where = "scenario_id = :scenario_id AND service = :service"
        params: dict[str, Any] = {"scenario_id": scenario_id, "service": service}
        if query:
            where += " AND lower(message || ' ' || fields_json) LIKE :query"
            params["query"] = f"%{query.lower()}%"
        if not self._post_action_visible(scenario_id, replay_instance_id):
            where += " AND ts <= :active_cutoff"
            params["active_cutoff"] = self._active_cutoff(scenario_id)
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

    def get_recent_changes(
        self,
        scenario_id: str,
        service: str,
        replay_instance_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        self.ensure_service(scenario_id, service)
        rows = self._all(
            """
            SELECT id, ts, service, kind, summary, details_json
            FROM changes
            WHERE scenario_id = :scenario_id AND service = :service
            ORDER BY ts
            """,
            scenario_id=scenario_id,
            service=service,
        )
        for row in rows:
            row["details"] = _loads(row.pop("details_json"), {})
            if not self._post_action_visible(scenario_id, replay_instance_id):
                row["details"].pop("rolled_back_at", None)
            elif row["id"] == "chg_checkout_pool_80":
                row["details"].setdefault(
                    "rolled_back_at",
                    self.get_replay_state(replay_instance_id)["updated_at"],
                )
        return rows

    def get_service_health(
        self,
        scenario_id: str,
        service: str,
        replay_instance_id: Optional[str] = None,
    ) -> dict[str, Any]:
        metrics = self.get_metrics(
            scenario_id,
            service,
            replay_instance_id=replay_instance_id,
        )
        logs = self.search_logs(
            scenario_id,
            service,
            replay_instance_id=replay_instance_id,
        )
        status = "healthy"
        signals: list[str] = []
        for metric in metrics:
            values = [point["value"] for point in metric["points"]]
            threshold = metric["threshold"]
            if threshold is not None and values and values[-1] >= threshold:
                status = "critical"
                signals.append(f"{metric['name']} is {values[-1]:g} {metric['unit']}")
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

    def get_replay_state(self, replay_instance_id: str) -> dict[str, Any]:
        return self._one(
            """
            SELECT id, scenario_id, status, checkout_db_pool_connections,
                   created_at, updated_at
            FROM replay_instances
            WHERE id = :replay_instance_id
            """,
            replay_instance_id=replay_instance_id,
        )

    def rollback_checkout_pool(self, replay_instance_id: str) -> dict[str, Any]:
        state = self.get_replay_state(replay_instance_id)
        if state["scenario_id"] != CHECKOUT_ROLLBACK_SCENARIO_ID:
            raise ValueError("Only checkout_db_pool_exhaustion supports replay mutation.")
        now = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as conn:
            update = conn.execute(
                text(
                    """
                    UPDATE replay_instances
                    SET status = 'mitigated',
                        checkout_db_pool_connections = 20,
                        updated_at = :updated_at
                    WHERE id = :replay_instance_id
                      AND scenario_id = :scenario_id
                      AND status = 'active'
                      AND checkout_db_pool_connections = 80
                    """
                ),
                {
                    "replay_instance_id": replay_instance_id,
                    "scenario_id": CHECKOUT_ROLLBACK_SCENARIO_ID,
                    "updated_at": now,
                },
            )
            if update.rowcount != 1:
                raise ValueError(
                    "Rollback requires an active replay instance with "
                    "checkout_db_pool_connections=80."
                )
        return self.get_replay_state(replay_instance_id)

    def _active_cutoff(self, scenario_id: str) -> str:
        row = self._one(
            "SELECT ended_at FROM incidents WHERE scenario_id = :scenario_id",
            scenario_id=scenario_id,
        )
        return row["ended_at"]

    def _post_action_visible(
        self,
        scenario_id: str,
        replay_instance_id: Optional[str],
    ) -> bool:
        if replay_instance_id is None:
            return False
        state = self.get_replay_state(replay_instance_id)
        if state["scenario_id"] != internal_scenario_id(scenario_id):
            raise ValueError("Replay instance does not belong to the requested scenario.")
        return state["status"] == "mitigated"

    def persist_run(
        self,
        scenario_id: str,
        replay_instance_id: str,
        trace: InvestigationTrace,
        evaluation: Optional[BehavioralEvaluation],
    ) -> str:
        run_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO investigation_runs
                    (id, scenario_id, replay_instance_id, agent_config_id,
                     status, created_at, updated_at, incident_id,
                     incident_description, final_root_cause, final_result_json,
                     hypotheses_json, prompt_version, tool_schema_version, model,
                     provider_metadata_json, error)
                    VALUES (:id, :scenario_id, :replay_instance_id,
                            :agent_config_id, 'completed', :created_at, :created_at,
                            :incident_id, :incident_description, :final_root_cause,
                            :final_result_json, :hypotheses_json, :prompt_version,
                            :tool_schema_version, :model, :provider_metadata_json,
                            NULL)
                    """
                ),
                {
                    "id": run_id,
                    "scenario_id": scenario_id,
                    "replay_instance_id": replay_instance_id,
                    "agent_config_id": trace.agent_config_id,
                    "created_at": created_at,
                    "incident_id": trace.incident_id,
                    "incident_description": trace.incident_description,
                    "final_root_cause": trace.final_root_cause,
                    "final_result_json": _dumps(trace.final_result),
                    "hypotheses_json": json.dumps(trace.hypotheses),
                    "prompt_version": trace.prompt_version,
                    "tool_schema_version": trace.tool_schema_version,
                    "model": trace.model,
                    "provider_metadata_json": _dumps(trace.provider_metadata),
                },
            )
            self._insert_trace_rows(conn, run_id, trace, evaluation)
        return run_id

    def create_pending_run(
        self,
        scenario_id: str,
        replay_instance_id: str,
        agent_config_id: str,
    ) -> str:
        """Create durable queued state before any worker is scheduled."""

        scenario_id = internal_scenario_id(scenario_id)
        incident = self.get_agent_context(scenario_id)
        run_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        symptoms = "; ".join(str(item) for item in incident.get("symptoms", []))
        incident_description = (
            f"{incident['title']}. Impact: {incident['customer_impact']} "
            f"Symptoms: {symptoms}"
        )
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO investigation_runs
                    (id, scenario_id, replay_instance_id, agent_config_id,
                     status, created_at, updated_at, incident_id,
                     incident_description, final_root_cause, final_result_json,
                     hypotheses_json, prompt_version, tool_schema_version, model,
                     provider_metadata_json, error)
                    VALUES (:id, :scenario_id, :replay_instance_id,
                            :agent_config_id, 'queued', :created_at, :created_at,
                            :incident_id, :incident_description, NULL, NULL, NULL,
                            NULL, NULL, NULL, NULL, NULL)
                    """
                ),
                {
                    "id": run_id,
                    "scenario_id": scenario_id,
                    "replay_instance_id": replay_instance_id,
                    "agent_config_id": agent_config_id,
                    "created_at": created_at,
                    "incident_id": incident["id"],
                    "incident_description": incident_description,
                },
            )
        return run_id

    def claim_run(self, run_id: str, started_payload: dict[str, Any]) -> bool:
        """Atomically claim a queued run and emit its single started event."""

        now = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as conn:
            claimed = conn.execute(
                text(
                    """
                    UPDATE investigation_runs
                    SET status = 'running', updated_at = :updated_at
                    WHERE id = :run_id AND status = 'queued'
                    """
                ),
                {"run_id": run_id, "updated_at": now},
            )
            if claimed.rowcount != 1:
                return False
            self._append_event_in_conn(
                conn,
                run_id,
                "investigation.started",
                "Investigation started",
                started_payload,
                created_at=now,
            )
        return True

    def append_event(
        self,
        run_id: str,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> InvestigationEvent:
        with self.engine.begin() as conn:
            status = conn.execute(
                text("SELECT status FROM investigation_runs WHERE id = :run_id"),
                {"run_id": run_id},
            ).scalar_one_or_none()
            if status is None:
                raise KeyError(f"Unknown investigation: {run_id}")
            if status != "running":
                raise ValueError("Progress events require a running investigation.")
            return self._append_event_in_conn(conn, run_id, event_type, summary, payload)

    def complete_run(
        self,
        run_id: str,
        trace: InvestigationTrace,
        evaluation: BehavioralEvaluation,
    ) -> None:
        """Persist the canonical response before the terminal completed event."""

        now = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as conn:
            completed = conn.execute(
                text(
                    """
                    UPDATE investigation_runs
                    SET status = 'completed', updated_at = :updated_at,
                        incident_id = :incident_id,
                        incident_description = :incident_description,
                        final_root_cause = :final_root_cause,
                        final_result_json = :final_result_json,
                        hypotheses_json = :hypotheses_json,
                        prompt_version = :prompt_version,
                        tool_schema_version = :tool_schema_version,
                        model = :model,
                        provider_metadata_json = :provider_metadata_json,
                        error = NULL
                    WHERE id = :run_id AND status = 'running'
                    """
                ),
                {
                    "run_id": run_id,
                    "updated_at": now,
                    "incident_id": trace.incident_id,
                    "incident_description": trace.incident_description,
                    "final_root_cause": trace.final_root_cause,
                    "final_result_json": _dumps(trace.final_result),
                    "hypotheses_json": json.dumps(trace.hypotheses),
                    "prompt_version": trace.prompt_version,
                    "tool_schema_version": trace.tool_schema_version,
                    "model": trace.model,
                    "provider_metadata_json": _dumps(trace.provider_metadata),
                },
            )
            if completed.rowcount != 1:
                raise ValueError("Only a running investigation can complete.")
            self._insert_trace_rows(conn, run_id, trace, evaluation)
            if trace.final_result.action_proposal is not None:
                self._insert_initial_action_proposal(
                    conn,
                    run_id,
                    trace.final_result.action_proposal,
                    trace.tool_calls,
                )
            self._append_event_in_conn(
                conn,
                run_id,
                "investigation.completed",
                "Investigation completed",
                {"tool_call_count": len(trace.tool_calls)},
                created_at=now,
            )

    def fail_run(self, run_id: str, error: str) -> bool:
        """Persist one sanitized failure and its terminal event."""

        now = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as conn:
            failed = conn.execute(
                text(
                    """
                    UPDATE investigation_runs
                    SET status = 'failed', updated_at = :updated_at, error = :error
                    WHERE id = :run_id AND status IN ('queued', 'running')
                    """
                ),
                {"run_id": run_id, "updated_at": now, "error": error},
            )
            if failed.rowcount != 1:
                return False
            self._append_event_in_conn(
                conn,
                run_id,
                "investigation.failed",
                "Investigation failed",
                {"error": error},
                created_at=now,
            )
        return True

    def get_run_status(self, run_id: str) -> InvestigationRunStatus:
        row = self._one(
            """
            SELECT id, scenario_id, status, error
            FROM investigation_runs
            WHERE id = :run_id
            """,
            run_id=run_id,
        )
        response: Optional[InvestigationResponse] = None
        follow_ups: list[InvestigationFollowUpExchange] = []
        action_result: Optional[ActionConfirmationResponse] = None
        if row["status"] == "completed":
            response = InvestigationResponse(
                run_id=run_id,
                trace=self.get_run(run_id),
                evaluation=self.get_evaluation(run_id),
            )
            follow_ups = self.get_follow_up_exchanges(run_id)
            action_result = self.get_executed_action_result(run_id)
        return InvestigationRunStatus(
            run_id=run_id,
            scenario_id=public_scenario_id(row["scenario_id"]),
            status=row["status"],
            response=response,
            error=row["error"],
            follow_ups=follow_ups,
            action_result=action_result,
        )

    def list_investigations(self, limit: int = 50) -> list[InvestigationSummary]:
        """Return bounded, public run metadata without loading trace or evaluator data."""

        limit = min(max(limit, 0), 50)
        rows = self._all(
            """
            SELECT runs.id AS run_id, runs.scenario_id,
                   incidents.id AS incident_id,
                   incidents.title AS incident_title,
                   runs.status,
                   CASE
                       WHEN runs.status = 'completed'
                       THEN json_extract(runs.final_result_json, '$.outcome')
                       ELSE NULL
                   END AS outcome,
                   runs.created_at, runs.updated_at
            FROM investigation_runs AS runs
            JOIN incidents
              ON incidents.scenario_id = runs.scenario_id
             AND incidents.id = runs.incident_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM comparisons
                WHERE comparisons.baseline_run_id = runs.id
                   OR comparisons.candidate_run_id = runs.id
            )
            ORDER BY runs.created_at DESC, runs.id DESC
            LIMIT :limit
            """,
            limit=limit,
        )
        return [
            InvestigationSummary(
                **(row | {"scenario_id": public_scenario_id(row["scenario_id"])})
            )
            for row in rows
        ]

    def list_events(self, run_id: str, after: int = 0) -> list[InvestigationEvent]:
        self.get_run_status(run_id)
        rows = self._all(
            """
            SELECT event_id, created_at, type, summary, payload_json
            FROM investigation_events
            WHERE run_id = :run_id AND event_id > :after
            ORDER BY event_id
            """,
            run_id=run_id,
            after=after,
        )
        return [
            InvestigationEvent(
                id=row["event_id"],
                run_id=run_id,
                type=row["type"],
                created_at=row["created_at"],
                summary=row["summary"],
                payload=_loads(row["payload_json"], {}),
            )
            for row in rows
        ]

    def get_run_metadata(self, run_id: str) -> dict[str, Any]:
        return self._one(
            """
            SELECT scenario_id, replay_instance_id, agent_config_id, status
            FROM investigation_runs
            WHERE id = :run_id
            """,
            run_id=run_id,
        )

    def _insert_initial_action_proposal(
        self,
        conn: Any,
        run_id: str,
        proposal: ActionProposal,
        tool_calls: list[ToolCall],
    ) -> None:
        scope = conn.execute(
            text("SELECT scenario_id FROM investigation_runs WHERE id = :run_id"),
            {"run_id": run_id},
        ).mappings().one()
        if scope["scenario_id"] != CHECKOUT_ROLLBACK_SCENARIO_ID:
            raise ValueError("Rollback proposals are only allowed for checkout_db_pool_exhaustion.")
        if (
            proposal.action_name != "rollback_configuration"
            or proposal.arguments != CHECKOUT_ROLLBACK_ARGUMENTS
            or proposal.expected_impact != CHECKOUT_ROLLBACK_EXPECTED_IMPACT
        ):
            raise ValueError("Unsupported rollback proposal.")
        retrieved = {
            evidence_id
            for call in tool_calls
            if call.status == "ok"
            for evidence_id in call.evidence_ids
        }
        if CHECKOUT_ROLLBACK_EVIDENCE_ID not in retrieved:
            raise ValueError("Rollback proposal requires retrieved configuration-change evidence.")
        conn.execute(
            text(
                """
                INSERT INTO action_proposals
                (id, run_id, action_name, arguments_json, expected_impact,
                 status, result_json, verification_status,
                 verification_tool_calls_json)
                VALUES (:id, :run_id, :action_name, :arguments_json,
                        :expected_impact, 'proposed', NULL, 'pending', '[]')
                """
            ),
            {
                "id": proposal.id,
                "run_id": run_id,
                "action_name": proposal.action_name,
                "arguments_json": json.dumps(proposal.arguments),
                "expected_impact": proposal.expected_impact,
            },
        )

    def _insert_trace_rows(
        self,
        conn: Any,
        run_id: str,
        trace: InvestigationTrace,
        evaluation: Optional[BehavioralEvaluation],
    ) -> None:
        for call in trace.tool_calls:
            conn.execute(
                text(
                    """
                    INSERT INTO tool_calls
                    (run_id, sequence, tool_name, purpose, arguments_json,
                     result_json, evidence_ids_json, status, duration_ms)
                    VALUES (:run_id, :sequence, :tool_name, :purpose,
                            :arguments_json, :result_json, :evidence_ids_json,
                            :status, :duration_ms)
                    """
                ),
                {
                    "run_id": run_id,
                    "sequence": call.sequence,
                    "tool_name": call.tool_name,
                    "purpose": call.purpose,
                    "arguments_json": json.dumps(call.arguments),
                    "result_json": json.dumps(call.result),
                    "evidence_ids_json": json.dumps(call.evidence_ids),
                    "status": call.status,
                    "duration_ms": call.duration_ms,
                },
            )
        if evaluation is not None:
            self._insert_evaluation(conn, run_id, evaluation)

    def _append_event_in_conn(
        self,
        conn: Any,
        run_id: str,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
        *,
        created_at: Optional[str] = None,
    ) -> InvestigationEvent:
        event_id = int(
            conn.execute(
                text(
                    """
                    SELECT COALESCE(MAX(event_id), 0) + 1
                    FROM investigation_events
                    WHERE run_id = :run_id
                    """
                ),
                {"run_id": run_id},
            ).scalar_one()
        )
        event = InvestigationEvent(
            id=event_id,
            run_id=run_id,
            type=event_type,
            created_at=created_at or datetime.now(timezone.utc).isoformat(),
            summary=summary,
            payload=payload,
        )
        conn.execute(
            text(
                """
                INSERT INTO investigation_events
                (run_id, event_id, created_at, type, summary, payload_json)
                VALUES (:run_id, :event_id, :created_at, :type, :summary,
                        :payload_json)
                """
            ),
            {
                "run_id": run_id,
                "event_id": event.id,
                "created_at": event.created_at,
                "type": event.type,
                "summary": event.summary,
                "payload_json": _dumps(event.payload),
            },
        )
        return event

    def persist_evaluation(self, run_id: str, evaluation: BehavioralEvaluation) -> None:
        with self.engine.begin() as conn:
            self._insert_evaluation(conn, run_id, evaluation)

    def _insert_evaluation(self, conn: Any, run_id: str, evaluation: BehavioralEvaluation) -> None:
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO evaluations
                (run_id, rca_correct, grounded, investigation_sufficient,
                 tool_efficient, behavioral_slo_pass, reasons_json)
                VALUES (:run_id, :rca_correct, :grounded,
                        :investigation_sufficient, :tool_efficient,
                        :behavioral_slo_pass, :reasons_json)
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

    def get_run(self, run_id: str) -> InvestigationTrace:
        run = self._one(
            """
            SELECT incident_id, incident_description, agent_config_id,
                   final_root_cause, final_result_json, hypotheses_json,
                   prompt_version, tool_schema_version, model,
                   provider_metadata_json
            FROM investigation_runs
            WHERE id = :run_id
            """,
            run_id=run_id,
        )
        calls = self._all(
            """
            SELECT sequence, tool_name, purpose, arguments_json, result_json,
                   evidence_ids_json, status, duration_ms
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
                purpose=row["purpose"],
                arguments=_loads(row["arguments_json"], {}),
                result=_loads(row["result_json"], {}),
                evidence_ids=_loads(row["evidence_ids_json"], []),
                status=row["status"],
                duration_ms=row["duration_ms"],
            )
            for row in calls
        ]
        return InvestigationTrace(
            incident_id=run["incident_id"],
            incident_description=run["incident_description"],
            agent_config_id=run["agent_config_id"],
            prompt_version=run["prompt_version"],
            tool_schema_version=run["tool_schema_version"],
            model=run["model"],
            hypotheses=_loads(run["hypotheses_json"], []),
            tool_calls=tool_calls,
            final_result=InvestigationFinalResult.model_validate(_loads(run["final_result_json"], {})),
            provider_metadata=ProviderMetadata.model_validate(_loads(run["provider_metadata_json"], {})),
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

    def get_run_scenario_id(self, run_id: str) -> str:
        return self.get_run_scope(run_id)["scenario_id"]

    def get_run_replay_instance_id(self, run_id: str) -> str:
        return self.get_run_scope(run_id)["replay_instance_id"]

    def get_run_scope(self, run_id: str) -> dict[str, str]:
        return self._one(
            """
            SELECT scenario_id, replay_instance_id
            FROM investigation_runs
            WHERE id = :run_id
            """,
            run_id=run_id,
        )

    def run_retrieved_evidence_ids(self, run_id: str) -> set[str]:
        retrieved: set[str] = set()
        rows = self._all(
            """
            SELECT evidence_ids_json
            FROM tool_calls
            WHERE run_id = :run_id AND status = 'ok'
            """,
            run_id=run_id,
        )
        for row in rows:
            retrieved.update(_loads(row["evidence_ids_json"], []))
        chat_rows = self._all(
            "SELECT tool_calls_json FROM chat_messages WHERE run_id = :run_id",
            run_id=run_id,
        )
        for row in chat_rows:
            for payload in _loads(row["tool_calls_json"], []):
                if payload.get("status") == "ok":
                    retrieved.update(payload.get("evidence_ids", []))
        return retrieved

    def persist_action_proposal(
        self,
        run_id: str,
        proposal: ActionProposal,
        additional_evidence_ids: Optional[set[str]] = None,
    ) -> None:
        scenario_id = self.get_run_scenario_id(run_id)
        if scenario_id != CHECKOUT_ROLLBACK_SCENARIO_ID:
            raise ValueError("Rollback proposals are only allowed for checkout_db_pool_exhaustion.")
        if (
            proposal.action_name != "rollback_configuration"
            or proposal.arguments != CHECKOUT_ROLLBACK_ARGUMENTS
            or proposal.expected_impact != CHECKOUT_ROLLBACK_EXPECTED_IMPACT
        ):
            raise ValueError("Unsupported rollback proposal.")
        retrieved = self.run_retrieved_evidence_ids(run_id)
        retrieved.update(additional_evidence_ids or set())
        if CHECKOUT_ROLLBACK_EVIDENCE_ID not in retrieved:
            raise ValueError("Rollback proposal requires retrieved configuration-change evidence.")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO action_proposals
                    (id, run_id, action_name, arguments_json, expected_impact,
                     status, result_json, verification_status,
                     verification_tool_calls_json)
                    VALUES (:id, :run_id, :action_name, :arguments_json,
                            :expected_impact, :status, :result_json,
                            :verification_status, :verification_tool_calls_json)
                    """
                ),
                {
                    "id": proposal.id,
                    "run_id": run_id,
                    "action_name": proposal.action_name,
                    "arguments_json": json.dumps(proposal.arguments),
                    "expected_impact": proposal.expected_impact,
                    "status": "proposed",
                    "result_json": None,
                    "verification_status": "pending",
                    "verification_tool_calls_json": "[]",
                },
            )

    def get_action_proposal(self, proposal_id: str) -> tuple[str, ActionProposal, str]:
        row = self._one(
            """
            SELECT id, run_id, action_name, arguments_json, expected_impact,
                   status, verification_status
            FROM action_proposals
            WHERE id = :proposal_id
            """,
            proposal_id=proposal_id,
        )
        proposal = ActionProposal(
            id=row["id"],
            action_name=row["action_name"],
            arguments=_loads(row["arguments_json"], {}),
            expected_impact=row["expected_impact"],
            status=row["status"],
        )
        return row["run_id"], proposal, row["verification_status"]

    def persist_action_result(
        self,
        run_id: str,
        proposal: ActionProposal,
        verification_status: str,
        result: dict[str, Any],
        verification_tool_calls: list[ToolCall],
        recovery_assessment: Optional[RecoveryAssessment],
        agent_assessment_error: Optional[str],
    ) -> ActionConfirmationResponse:
        proposal = proposal.model_copy(update={"status": "executed"})
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE action_proposals
                    SET status = 'executed',
                        result_json = :result_json,
                        verification_status = :verification_status,
                        verification_tool_calls_json = :verification_tool_calls_json,
                        recovery_assessment_json = :recovery_assessment_json,
                        agent_assessment_error = :agent_assessment_error
                    WHERE id = :id
                    """
                ),
                {
                    "id": proposal.id,
                    "result_json": json.dumps(result),
                    "verification_status": verification_status,
                    "verification_tool_calls_json": _dumps(verification_tool_calls),
                    "recovery_assessment_json": (
                        _dumps(recovery_assessment) if recovery_assessment is not None else None
                    ),
                    "agent_assessment_error": agent_assessment_error,
                },
            )
        return ActionConfirmationResponse(
            run_id=run_id,
            proposal=proposal,
            verification_status=verification_status,
            result=result,
            verification_tool_calls=verification_tool_calls,
            recovery_assessment=recovery_assessment,
            agent_assessment_error=agent_assessment_error,
        )

    def get_action_result(self, proposal_id: str) -> ActionConfirmationResponse:
        row = self._one(
            """
            SELECT run_id, id, action_name, arguments_json, expected_impact,
                   status, result_json, verification_status,
                   verification_tool_calls_json, recovery_assessment_json,
                   agent_assessment_error
            FROM action_proposals
            WHERE id = :proposal_id
            """,
            proposal_id=proposal_id,
        )
        proposal = ActionProposal(
            id=row["id"],
            action_name=row["action_name"],
            arguments=_loads(row["arguments_json"], {}),
            expected_impact=row["expected_impact"],
            status=row["status"],
        )
        return ActionConfirmationResponse(
            run_id=row["run_id"],
            proposal=proposal,
            verification_status=row["verification_status"],
            result=_loads(row["result_json"], {}),
            verification_tool_calls=[
                ToolCall.model_validate(item)
                for item in _loads(row["verification_tool_calls_json"], [])
            ],
            recovery_assessment=(
                RecoveryAssessment.model_validate(_loads(row["recovery_assessment_json"], {}))
                if row["recovery_assessment_json"]
                else None
            ),
            agent_assessment_error=row["agent_assessment_error"],
        )

    def get_executed_action_result(
        self,
        run_id: str,
    ) -> Optional[ActionConfirmationResponse]:
        rows = self._all(
            """
            SELECT id
            FROM action_proposals
            WHERE run_id = :run_id AND status = 'executed'
            ORDER BY id
            """,
            run_id=run_id,
        )
        if not rows:
            return None
        if len(rows) > 1:
            raise ValueError("Investigation has more than one executed action result.")
        return self.get_action_result(rows[0]["id"])

    def persist_chat_response(self, response: ChatMessageResponse) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO chat_messages
                    (run_id, role, content, evidence_ids_json, tool_calls_json,
                     action_proposal_id)
                    VALUES (:run_id, 'agent', :content, :evidence_ids_json,
                            :tool_calls_json, :action_proposal_id)
                    """
                ),
                {
                    "run_id": response.run_id,
                    "content": response.message,
                    "evidence_ids_json": json.dumps(response.evidence_ids),
                    "tool_calls_json": _dumps(response.tool_calls),
                    "action_proposal_id": response.action_proposal.id if response.action_proposal else None,
                },
            )

    def persist_chat_user_message(self, run_id: str, message: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO chat_messages
                    (run_id, role, content, evidence_ids_json, tool_calls_json,
                     action_proposal_id)
                    VALUES (:run_id, 'user', :content, '[]', '[]', NULL)
                    """
                ),
                {"run_id": run_id, "content": message},
            )

    def get_chat_messages(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._all(
            """
            SELECT role, content, evidence_ids_json, tool_calls_json,
                   action_proposal_id
            FROM chat_messages
            WHERE run_id = :run_id
            ORDER BY id
            """,
            run_id=run_id,
        )
        for row in rows:
            row["evidence_ids"] = _loads(row.pop("evidence_ids_json"), [])
            row["tool_calls"] = _loads(row.pop("tool_calls_json"), [])
        return rows

    def get_follow_up_exchanges(
        self,
        run_id: str,
    ) -> list[InvestigationFollowUpExchange]:
        exchanges: list[InvestigationFollowUpExchange] = []
        pending_question: Optional[str] = None
        for message in self.get_chat_messages(run_id):
            if message["role"] == "user":
                pending_question = message["content"]
                continue
            if message["role"] != "agent":
                raise ValueError("Investigation transcript has an unsupported role.")
            if pending_question is None:
                raise ValueError("Investigation transcript has an unpaired agent response.")
            proposal: Optional[ActionProposal] = None
            proposal_id = message["action_proposal_id"]
            if proposal_id is not None:
                proposal_run_id, proposal, _verification = self.get_action_proposal(
                    proposal_id
                )
                if proposal_run_id != run_id:
                    raise ValueError("Transcript action proposal belongs to another run.")
            response = ChatMessageResponse(
                run_id=run_id,
                message=message["content"],
                evidence_ids=message["evidence_ids"],
                tool_calls=[
                    ToolCall.model_validate(tool_call)
                    for tool_call in message["tool_calls"]
                ],
                action_proposal=proposal,
            )
            exchanges.append(
                InvestigationFollowUpExchange(
                    question=pending_question,
                    response=response,
                )
            )
            pending_question = None
        return exchanges

    def get_action_state(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._all(
            """
            SELECT id, action_name, arguments_json, expected_impact, status,
                   result_json, verification_status,
                   verification_tool_calls_json, recovery_assessment_json,
                   agent_assessment_error
            FROM action_proposals
            WHERE run_id = :run_id
            ORDER BY id
            """,
            run_id=run_id,
        )
        for row in rows:
            row["arguments"] = _loads(row.pop("arguments_json"), {})
            row["result"] = _loads(row.pop("result_json"), {})
            row["verification_tool_calls"] = _loads(row.pop("verification_tool_calls_json"), [])
            row["recovery_assessment"] = _loads(row.pop("recovery_assessment_json"), None)
        return rows

    def count_context_tool_calls(self, run_id: str) -> int:
        run_count = self._one(
            "SELECT COUNT(*) AS count FROM tool_calls WHERE run_id = :run_id AND status = 'ok'",
            run_id=run_id,
        )["count"]
        chat_rows = self._all(
            "SELECT tool_calls_json FROM chat_messages WHERE run_id = :run_id",
            run_id=run_id,
        )
        chat_count = 0
        for row in chat_rows:
            chat_count += sum(1 for call in _loads(row["tool_calls_json"], []) if call.get("status") == "ok")
        return int(run_count) + chat_count

    def persist_comparison(
        self,
        scenario_id: str,
        baseline: InvestigationResponse,
        candidate: InvestigationResponse,
    ) -> str:
        comparison_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO comparisons
                    (id, scenario_id, created_at, baseline_run_id, candidate_run_id)
                    VALUES (:id, :scenario_id, :created_at, :baseline_run_id,
                            :candidate_run_id)
                    """
                ),
                {
                    "id": comparison_id,
                    "scenario_id": scenario_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "baseline_run_id": baseline.run_id,
                    "candidate_run_id": candidate.run_id,
                },
            )
        return comparison_id

    def list_comparisons(self, limit: int = 50) -> list[ComparisonSummary]:
        """Return bounded comparison metadata without loading either run trace."""

        limit = min(max(limit, 0), 50)
        rows = self._all(
            """
            SELECT comparisons.id AS comparison_id,
                   comparisons.scenario_id,
                   incidents.id AS incident_id,
                   incidents.title AS incident_title,
                   comparisons.created_at
            FROM comparisons
            JOIN incidents
              ON incidents.scenario_id = comparisons.scenario_id
            ORDER BY comparisons.created_at DESC, comparisons.id DESC
            LIMIT :limit
            """,
            limit=limit,
        )
        return [
            ComparisonSummary(
                **(row | {"scenario_id": public_scenario_id(row["scenario_id"])})
            )
            for row in rows
        ]

    def get_comparison(self, comparison_id: str) -> ComparisonResponse:
        row = self._one(
            """
            SELECT id, scenario_id, baseline_run_id, candidate_run_id
            FROM comparisons
            WHERE id = :comparison_id
            """,
            comparison_id=comparison_id,
        )
        baseline = InvestigationResponse(
            run_id=row["baseline_run_id"],
            trace=self.get_run(row["baseline_run_id"]),
            evaluation=self.get_evaluation(row["baseline_run_id"]),
        )
        candidate = InvestigationResponse(
            run_id=row["candidate_run_id"],
            trace=self.get_run(row["candidate_run_id"]),
            evaluation=self.get_evaluation(row["candidate_run_id"]),
        )
        return ComparisonResponse(
            comparison_id=row["id"],
            scenario_id=public_scenario_id(row["scenario_id"]),
            baseline=baseline,
            candidate=candidate,
        )

    def _one(self, sql: str, **params: Any) -> dict[str, Any]:
        rows = self._all(sql, **params)
        if not rows:
            raise KeyError(f"No row for query: {sql.strip()} params={params}")
        return rows[0]

    def _all(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text(sql), params).mappings().all()]


def internal_scenario_id(scenario_id: str) -> str:
    return INTERNAL_SCENARIO_IDS.get(scenario_id, scenario_id)


def public_scenario_id(scenario_id: str) -> str:
    return PUBLIC_SCENARIO_IDS.get(scenario_id, scenario_id)


def public_scenario_name(scenario_id: str) -> str:
    return PUBLIC_SCENARIO_NAMES.get(scenario_id, scenario_id)
