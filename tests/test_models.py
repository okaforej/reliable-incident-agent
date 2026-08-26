from __future__ import annotations

import pytest
from conftest import (
    SCENARIO_ID,
    dump_model,
    import_model,
    make_trace,
    strong_evidence_tool_calls,
    validate_model,
)
from pydantic import ValidationError


def test_pydantic_models_validate_investigation_contracts() -> None:
    InvestigationRequest = import_model("InvestigationRequest")
    InvestigationResponse = import_model("InvestigationResponse")
    BehavioralEvaluation = import_model("BehavioralEvaluation")

    trace = make_trace(strong_evidence_tool_calls())
    evaluation = validate_model(
        BehavioralEvaluation,
        {
            "rca_correct": True,
            "grounded": True,
            "investigation_sufficient": True,
            "tool_efficient": True,
            "behavioral_slo_pass": True,
            "reasons": ["Trace is grounded."],
        },
    )
    request = validate_model(
        InvestigationRequest,
        {"scenario_id": SCENARIO_ID, "mode": "baseline"},
    )
    response = validate_model(
        InvestigationResponse,
        {
            "run_id": "run-1",
            "trace": dump_model(trace),
            "evaluation": dump_model(evaluation),
        },
    )

    assert request.mode == "baseline"
    assert response.trace.final_result.outcome == "root_cause"
    assert response.trace.provider_metadata.provider == "fake"


def test_pydantic_models_validate_chat_action_and_comparison_contracts() -> None:
    ChatMessageResponse = import_model("ChatMessageResponse")
    ActionConfirmationResponse = import_model("ActionConfirmationResponse")
    ComparisonRequest = import_model("ComparisonRequest")

    chat = validate_model(
        ChatMessageResponse,
        {
            "run_id": "run-1",
            "message": "Payments was collateral.",
            "evidence_ids": ["log_payments_upstream_cancelled"],
            "tool_calls": [],
            "action_proposal": {
                "id": "act-1",
                "action_name": "rollback_configuration",
                "arguments": {
                    "service": "checkout",
                    "config_key": "db.max_open_connections",
                    "from_value": 80,
                    "to_value": 20,
                },
                "expected_impact": "Restore prior pool limit.",
            },
        },
    )
    action = validate_model(
        ActionConfirmationResponse,
        {
            "run_id": "run-1",
            "proposal": dump_model(chat.action_proposal),
            "verification_status": "verified",
            "result": {"status": "mitigated"},
            "verification_tool_calls": [],
            "recovery_assessment": {
                "conclusion": "recovered",
                "summary": "Verification telemetry is below threshold.",
                "evidence_ids": ["metric_checkout_latency"],
                "remaining_risks": ["Continue monitoring."],
            },
            "agent_assessment_error": None,
        },
    )
    comparison = validate_model(ComparisonRequest, {"scenario_id": SCENARIO_ID})

    assert chat.action_proposal.requires_confirmation is True
    assert action.proposal.action_name == "rollback_configuration"
    assert action.recovery_assessment.conclusion == "recovered"
    assert comparison.scenario_id == SCENARIO_ID


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


def test_health_contract_is_strict_and_chat_message_is_trimmed() -> None:
    HealthResponse = import_model("HealthResponse")
    ChatMessageRequest = import_model("ChatMessageRequest")

    health = validate_model(
        HealthResponse,
        {
            "status": "ok",
            "openai_api_key_configured": False,
            "openai_model": None,
        },
    )
    message = validate_model(ChatMessageRequest, {"message": "  What changed?  "})

    assert health.status == "ok"
    assert message.message == "What changed?"

    with pytest.raises(ValidationError):
        validate_model(ChatMessageRequest, {"message": "   \n\t"})
    with pytest.raises(ValidationError):
        validate_model(
            HealthResponse,
            {
                "status": "ok",
                "openai_api_key_configured": False,
                "openai_model": None,
                "provider_ready": False,
            },
        )
