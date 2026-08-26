from __future__ import annotations

from conftest import (
    EXPECTED_RCA,
    evaluate_trace,
    expected_outcome,
    get_attr,
    make_tool_call,
    make_trace,
    strong_evidence_tool_calls,
)


def test_evaluator_ignores_hidden_evidence_not_retrieved_by_tool_calls() -> None:
    trace = make_trace(
        [
            make_tool_call(
                1,
                "get_service_health",
                {
                    "evidence_id": "health-checkout",
                    "service": "checkout",
                    "status": "degraded",
                    "symptoms": ["high_latency"],
                },
                {"service": "checkout"},
            )
        ],
        final_root_cause=EXPECTED_RCA,
    )

    evaluation = evaluate_trace(trace, expected_outcome())

    assert get_attr(evaluation, "rca_correct") is True
    assert get_attr(evaluation, "behavioral_slo_pass") is False
    assert (
        get_attr(evaluation, "grounded") is False
        or get_attr(evaluation, "investigation_sufficient") is False
    )


def test_incorrect_rca_fails_correctness_without_masking_behavioral_fields() -> None:
    trace = make_trace(
        strong_evidence_tool_calls(),
        final_root_cause="Checkout latency was caused by a payments provider outage.",
    )

    evaluation = evaluate_trace(trace, expected_outcome())

    assert get_attr(evaluation, "rca_correct") is False
    assert isinstance(get_attr(evaluation, "grounded"), bool)
    assert isinstance(get_attr(evaluation, "investigation_sufficient"), bool)
    assert get_attr(evaluation, "tool_efficient") is True


def test_strong_observed_evidence_passes_behavioral_slo() -> None:
    trace = make_trace(strong_evidence_tool_calls())

    evaluation = evaluate_trace(trace, expected_outcome())

    assert get_attr(evaluation, "grounded") is True
    assert get_attr(evaluation, "investigation_sufficient") is True
    assert get_attr(evaluation, "tool_efficient") is True
    assert get_attr(evaluation, "behavioral_slo_pass") is True


def test_duplicate_tool_call_fails_efficiency_only() -> None:
    calls = strong_evidence_tool_calls()
    duplicate = make_tool_call(
        6,
        calls[0].tool_name,
        calls[0].result,
        calls[0].arguments,
    )
    trace = make_trace([*calls, duplicate])

    evaluation = evaluate_trace(trace, expected_outcome())

    assert get_attr(evaluation, "grounded") is True
    assert get_attr(evaluation, "investigation_sufficient") is True
    assert get_attr(evaluation, "tool_efficient") is False
    assert get_attr(evaluation, "behavioral_slo_pass") is False


def test_valid_investigation_does_not_require_exact_tool_order() -> None:
    calls = strong_evidence_tool_calls()
    reordered = [calls[index] for index in (3, 0, 4, 2, 1)]
    resequenced = [
        make_tool_call(
            sequence,
            call.tool_name,
            call.result,
            call.arguments,
        )
        for sequence, call in enumerate(reordered, start=1)
    ]

    evaluation = evaluate_trace(make_trace(resequenced), expected_outcome())

    assert get_attr(evaluation, "behavioral_slo_pass") is True


def test_evaluator_reports_behavior_without_prejudging_configuration() -> None:
    evaluation = evaluate_trace(
        make_trace(strong_evidence_tool_calls()),
        expected_outcome(),
    )

    reasons = " ".join(get_attr(evaluation, "reasons")).lower()
    assert all(
        label not in reasons
        for label in ("baseline", "candidate", "version a", "version b")
    )
