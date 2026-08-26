from __future__ import annotations

import pytest
from conftest import (
    EXPECTED_RCA,
    SCENARIO_ID,
    dump_model,
    import_model,
    make_tool_call,
    validate_model,
)
from pydantic import ValidationError


def test_pydantic_models_validate_trace_evaluation_request_and_response() -> None:
    InvestigationTrace = import_model("InvestigationTrace")
    BehavioralEvaluation = import_model("BehavioralEvaluation")
    InvestigationRequest = import_model("InvestigationRequest")
    InvestigationResponse = import_model("InvestigationResponse")

    tool_call = make_tool_call(
        sequence=1,
        tool_name="get_service_health",
        arguments={"service": "checkout"},
        result={"evidence_id": "health-checkout", "status": "degraded"},
    )
    trace = validate_model(
        InvestigationTrace,
        {
            "incident_id": SCENARIO_ID,
            "incident_description": "Checkout latency regression.",
            "tool_calls": [dump_model(tool_call)],
            "final_root_cause": EXPECTED_RCA,
        },
    )
    evaluation = validate_model(
        BehavioralEvaluation,
        {
            "rca_correct": True,
            "grounded": True,
            "investigation_sufficient": True,
            "tool_efficient": True,
            "behavioral_slo_pass": True,
            "reasons": ["RCA is supported by retrieved postgres saturation evidence."],
        },
    )
    request = validate_model(
        InvestigationRequest,
        {"scenario_id": SCENARIO_ID, "mode": "reliable"},
    )
    response = validate_model(
        InvestigationResponse,
        {
            "run_id": "run-reliable-1",
            "trace": dump_model(trace),
            "evaluation": dump_model(evaluation),
        },
    )

    assert request.mode == "reliable"
    assert response.trace.final_root_cause == EXPECTED_RCA
    assert response.evaluation.behavioral_slo_pass is True


def test_pydantic_models_reject_invalid_investigation_mode() -> None:
    InvestigationRequest = import_model("InvestigationRequest")

    with pytest.raises(ValidationError):
        validate_model(
            InvestigationRequest,
            {"scenario_id": SCENARIO_ID, "mode": "shortcut"},
        )


def test_pydantic_models_reject_unexpected_evaluation_fields() -> None:
    BehavioralEvaluation = import_model("BehavioralEvaluation")

    with pytest.raises(ValidationError):
        validate_model(
            BehavioralEvaluation,
            {
                "rca_correct": True,
                "grounded": True,
                "investigation_sufficient": True,
                "tool_efficient": True,
                "behavioral_slo_pass": True,
                "confidence_score": 0.99,
            },
        )
