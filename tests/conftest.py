from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
    assert hasattr(models, model_name), (
        f"Expected reliable_incident_agent.models.{model_name} to be defined "
        "as part of the PRD public contract."
    )
    return getattr(models, model_name)


def validate_model(model_cls: type, payload: dict[str, Any]) -> Any:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)
    return model_cls(**payload)


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
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


def build_request(mode: str) -> Any:
    InvestigationRequest = import_model("InvestigationRequest")
    return validate_model(
        InvestigationRequest,
        {"scenario_id": SCENARIO_ID, "mode": mode},
    )


def run_investigation(mode: str) -> Any:
    investigator = import_module("investigator")
    candidates = ("run_investigation", "investigate", "run")
    run_func = next(
        (getattr(investigator, name) for name in candidates if hasattr(investigator, name)),
        None,
    )
    assert run_func is not None, (
        "Expected reliable_incident_agent.investigator to expose one of: "
        f"{', '.join(candidates)}."
    )

    request = build_request(mode)
    signature = inspect.signature(run_func)
    if len(signature.parameters) == 1:
        result = run_func(request)
    else:
        result = run_func(scenario_id=SCENARIO_ID, mode=mode)

    if hasattr(result, "trace") or (isinstance(result, dict) and "trace" in result):
        return result

    evaluation = evaluate_trace(result, expected_outcome())
    return SimpleNamespace(
        run_id=f"contract-test-{mode}",
        trace=result,
        evaluation=evaluation,
    )


def evaluate_trace(trace: Any, expected_outcome: Any) -> Any:
    evaluator = import_module("evaluator")
    candidates = ("evaluate_trace", "evaluate_behavior", "evaluate")
    evaluate_func = next(
        (getattr(evaluator, name) for name in candidates if hasattr(evaluator, name)),
        None,
    )
    assert evaluate_func is not None, (
        "Expected reliable_incident_agent.evaluator to expose one of: "
        f"{', '.join(candidates)}."
    )
    return evaluate_func(trace, expected_outcome)


def make_tool_call(
    sequence: int,
    tool_name: str,
    result: dict[str, Any],
    arguments: dict[str, Any] | None = None,
) -> Any:
    ToolCall = import_model("ToolCall")
    return validate_model(
        ToolCall,
        {
            "sequence": sequence,
            "tool_name": tool_name,
            "arguments": arguments or {},
            "result": result,
        },
    )


def make_trace(tool_calls: list[Any], final_root_cause: str = EXPECTED_RCA) -> Any:
    InvestigationTrace = import_model("InvestigationTrace")
    return validate_model(
        InvestigationTrace,
        {
            "incident_id": SCENARIO_ID,
            "incident_description": (
                "Checkout latency and elevated payment errors during the "
                "checkout_db_pool_exhaustion replay."
            ),
            "tool_calls": [dump_model(call) for call in tool_calls],
            "final_root_cause": final_root_cause,
        },
    )


def expected_outcome(root_cause: str = EXPECTED_RCA) -> Any:
    ExpectedOutcome = import_model("ExpectedOutcome")
    return validate_model(ExpectedOutcome, {"root_cause": root_cause})


def strong_evidence_tool_calls() -> list[Any]:
    return [
        make_tool_call(
            1,
            "get_service_health",
            {
                "evidence_id": "health-checkout-incident",
                "service": "checkout",
                "status": "degraded",
                "latency_p95_ms": 2400,
                "symptoms": ["db_wait", "request_queueing"],
            },
            {"service": "checkout"},
        ),
        make_tool_call(
            2,
            "get_dependencies",
            {
                "evidence_id": "deps-checkout",
                "service": "checkout",
                "dependencies": ["postgres", "payments"],
                "postgres_role": "primary checkout datastore",
            },
            {"service": "checkout"},
        ),
        make_tool_call(
            3,
            "get_metrics",
            {
                "evidence_id": "metric-postgres-connections",
                "service": "postgres",
                "metric_name": "active_connections",
                "metrics": [
                    {
                        "name": "db.connections.active",
                        "points": [
                            {"ts": "2026-08-25T10:01:00Z", "value": 78},
                            {"ts": "2026-08-25T10:03:00Z", "value": 80},
                        ],
                    }
                ],
                "limit": 80,
                "interpretation": "postgres connection pool saturated at 80 of 80",
            },
            {"service": "postgres", "metric_name": "active_connections"},
        ),
        make_tool_call(
            4,
            "get_recent_changes",
            {
                "evidence_id": "change-checkout-db-pool",
                "service": "checkout",
                "changes": [
                    {
                        "component": "database_pool",
                        "field": "max_open_connections",
                        "from": 20,
                        "to": 80,
                        "deployed_at": "2026-08-25T09:55:00Z",
                    }
                ],
            },
            {"service": "checkout"},
        ),
        make_tool_call(
            5,
            "search_logs",
            {
                "evidence_id": "logs-checkout-db-wait",
                "service": "checkout",
                "matches": [
                    {
                        "message": "waiting for postgres connection",
                        "fields": {"pool": "orders"},
                    },
                    {
                        "message": "database connection pool exhausted",
                        "fields": {"active_connections": 80},
                    },
                    {
                        "message": "payments errors begin after checkout queueing",
                        "fields": {"upstream": "checkout"},
                    },
                ],
            },
            {"service": "checkout", "query": "postgres connection"},
        ),
    ]
