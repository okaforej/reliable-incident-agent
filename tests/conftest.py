from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

SCENARIO_ID = "checkout_db_pool_exhaustion"
EXPECTED_RCA = (
    "Checkout latency was caused by postgres connection exhaustion after "
    "checkout deployed a database pool max_open_connections change from 20 to 80."
)


def import_module(module_name: str) -> Any:
    return importlib.import_module(f"reliable_incident_agent.{module_name}")


def import_model(model_name: str) -> type:
    models = import_module("models")
    assert hasattr(models, model_name)
    return getattr(models, model_name)


def validate_model(model_cls: type, payload: dict[str, Any]) -> Any:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)
    return model_cls(**payload)


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return model


def get_attr(obj: Any, path: str) -> Any:
    current = obj
    for part in path.split("."):
        if isinstance(current, dict):
            current = current[part]
        else:
            current = getattr(current, part)
    return current


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tests from the local-dev database and from each other."""

    db = import_module("db")
    test_db_path = tmp_path / "replays.sqlite"
    monkeypatch.setattr(db, "DB_PATH", test_db_path)
    api = sys.modules.get("reliable_incident_agent.api")
    if api is not None:
        monkeypatch.setattr(api, "DB_PATH", test_db_path)
    db.init_db(test_db_path)


def provider_result(
    *,
    response_id: str,
    tool_calls: Optional[list[Any]] = None,
    final: Optional[dict[str, Any]] = None,
) -> Any:
    providers = import_module("providers")
    return providers.ProviderResult(
        response_id=response_id,
        tool_calls=tool_calls or [],
        final=final,
    )


def provider_tool_call(
    name: str,
    arguments: dict[str, Any],
    call_id: str,
    purpose: str = "",
) -> Any:
    providers = import_module("providers")
    return providers.ProviderToolCall(
        name=name,
        arguments=arguments,
        call_id=call_id,
        purpose=purpose,
    )


def fake_provider(responses: list[Any]) -> Any:
    providers = import_module("providers")
    return providers.FakeModelProvider(responses)


def checkout_success_final(action: bool = False) -> dict[str, Any]:
    proposal = None
    if action:
        proposal = {
            "action_name": "rollback_configuration",
            "arguments": {
                "service": "checkout",
                "config_key": "db.max_open_connections",
                "from_value": 80,
                "to_value": 20,
            },
            "expected_impact": "Restore the prior checkout DB pool limit and reduce postgres saturation.",
        }
    return {
        "outcome": "root_cause",
        "root_cause": EXPECTED_RCA,
        "confidence": "high",
        "evidence_ids": [
            "metric_postgres_connections",
            "chg_checkout_pool_80",
            "log_checkout_pool_wait_timeout",
            "dep_checkout_postgres",
            "log_payments_upstream_cancelled",
        ],
        "hypothesis_summary": [
            {
                "hypothesis": "Postgres connection saturation caused checkout latency.",
                "status": "supported",
                "evidence_ids": ["metric_postgres_connections", "log_checkout_pool_wait_timeout"],
            },
            {
                "hypothesis": "Payments caused checkout failures.",
                "status": "weakened",
                "evidence_ids": ["log_payments_upstream_cancelled"],
            },
        ],
        "mitigation": "Rollback checkout db.max_open_connections to 20.",
        "verification_plan": [
            "Verify checkout latency returns to baseline.",
            "Verify postgres active connections fall below threshold.",
        ],
        "missing_evidence": [],
        "action_proposal": proposal,
    }


def checkout_provider(action: bool = False) -> Any:
    return fake_provider(
        [
            provider_result(
                response_id="resp-tools-1",
                tool_calls=[
                    provider_tool_call("get_service_health", {"service": "checkout"}, "call-1", "Check entry service health."),
                    provider_tool_call("get_dependencies", {"service": "checkout"}, "call-2", "Find plausible dependencies."),
                ],
            ),
            provider_result(
                response_id="resp-tools-2",
                tool_calls=[
                    provider_tool_call(
                        "get_metrics",
                        {"service": "postgres", "metric_name": "db.connections.active"},
                        "call-3",
                        "Test database saturation.",
                    ),
                    provider_tool_call("get_recent_changes", {"service": "checkout"}, "call-4", "Check checkout changes."),
                    provider_tool_call(
                        "search_logs",
                        {"service": "checkout", "query": "db acquire timeout"},
                        "call-5",
                        "Find checkout database wait logs.",
                    ),
                    provider_tool_call(
                        "search_logs",
                        {"service": "payments", "query": "cancelled"},
                        "call-6",
                        "Check whether payments is collateral.",
                    ),
                ],
            ),
            provider_result(response_id="resp-final", final=checkout_success_final(action=action)),
        ]
    )


def recovery_provider(
    *,
    conclusion: str = "recovered",
    evidence_ids: Optional[list[str]] = None,
) -> Any:
    return fake_provider(
        [
            provider_result(
                response_id="resp-recovery-assessment",
                final={
                    "conclusion": conclusion,
                    "summary": "Post-action telemetry is below the deterministic thresholds.",
                    "evidence_ids": evidence_ids or ["metric_checkout_latency"],
                    "remaining_risks": ["Continue watching checkout saturation."],
                },
            )
        ]
    )


def make_tool_call(
    sequence: int,
    tool_name: str,
    result: dict[str, Any],
    arguments: Optional[dict[str, Any]] = None,
    evidence_ids: Optional[list[str]] = None,
) -> Any:
    ToolCall = import_model("ToolCall")
    return validate_model(
        ToolCall,
        {
            "sequence": sequence,
            "tool_name": tool_name,
            "purpose": "",
            "arguments": arguments or {},
            "result": result,
            "evidence_ids": evidence_ids or _evidence_ids(result),
            "status": "ok",
            "duration_ms": 0,
        },
    )


def make_trace(tool_calls: list[Any], final_root_cause: str = EXPECTED_RCA) -> Any:
    InvestigationTrace = import_model("InvestigationTrace")
    ProviderMetadata = import_model("ProviderMetadata")
    InvestigationFinalResult = import_model("InvestigationFinalResult")
    final = InvestigationFinalResult.model_validate(
        checkout_success_final() | {"root_cause": final_root_cause, "evidence_ids": [e for c in tool_calls for e in c.evidence_ids]}
    )
    return validate_model(
        InvestigationTrace,
        {
            "incident_id": SCENARIO_ID,
            "incident_description": "Checkout latency and elevated errors.",
            "agent_config_id": "candidate",
            "prompt_version": "test",
            "tool_schema_version": "test",
            "model": "fake",
            "hypotheses": [item.hypothesis for item in final.hypothesis_summary],
            "tool_calls": [dump_model(call) for call in tool_calls],
            "final_result": dump_model(final),
            "provider_metadata": dump_model(ProviderMetadata(provider="fake", model="fake")),
            "final_root_cause": final_root_cause,
        },
    )


def expected_outcome(root_cause: str = EXPECTED_RCA) -> Any:
    ExpectedOutcome = import_model("ExpectedOutcome")
    return validate_model(ExpectedOutcome, {"root_cause": root_cause})


def evaluate_trace(trace: Any, expected: Any) -> Any:
    return import_module("evaluator").evaluate_trace(trace, expected)


def strong_evidence_tool_calls() -> list[Any]:
    return [
        make_tool_call(
            1,
            "get_service_health",
            {"service": "checkout", "status": "critical", "evidence_id": "health_checkout"},
            {"service": "checkout"},
        ),
        make_tool_call(
            2,
            "get_dependencies",
            {"service": "checkout", "dependencies": [{"id": "dep_checkout_postgres"}, {"id": "dep_checkout_payments"}]},
            {"service": "checkout"},
        ),
        make_tool_call(
            3,
            "get_metrics",
            {"service": "postgres", "metrics": [{"id": "metric_postgres_connections", "name": "db.connections.active", "points": [{"value": 100}]}]},
            {"service": "postgres", "metric_name": "db.connections.active"},
        ),
        make_tool_call(
            4,
            "get_recent_changes",
            {
                "service": "checkout",
                "changes": [
                    {
                        "id": "chg_checkout_pool_80",
                        "summary": "Increase checkout orders database pool size",
                        "details": {
                            "config_key": "db.max_open_connections",
                            "after": 80,
                            "before": 20,
                        },
                    }
                ],
            },
            {"service": "checkout"},
        ),
        make_tool_call(
            5,
            "search_logs",
            {"service": "checkout", "matches": [{"id": "log_checkout_pool_wait_timeout", "message": "db acquire timeout"}]},
            {"service": "checkout", "query": "db acquire timeout"},
        ),
        make_tool_call(
            6,
            "search_logs",
            {"service": "payments", "matches": [{"id": "log_payments_upstream_cancelled", "message": "request cancelled by upstream client"}]},
            {"service": "payments", "query": "cancelled"},
        ),
    ]


def _evidence_ids(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"id", "evidence_id"} and isinstance(child, str):
                found.append(child)
            else:
                found.extend(_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_evidence_ids(child))
    return sorted(set(found))
