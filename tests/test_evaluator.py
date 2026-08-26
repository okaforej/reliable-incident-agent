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
    assert get_attr(evaluation, "grounded") is False
    assert get_attr(evaluation, "investigation_sufficient") is False
    assert get_attr(evaluation, "tool_efficient") is True
    assert get_attr(evaluation, "behavioral_slo_pass") is False


def test_incorrect_rca_fails_correctness_without_masking_behavioral_fields() -> None:
    trace = make_trace(
        strong_evidence_tool_calls(),
        final_root_cause="Checkout latency was caused by a payments provider outage.",
    )

    evaluation = evaluate_trace(trace, expected_outcome())

    assert get_attr(evaluation, "rca_correct") is False
    assert get_attr(evaluation, "grounded") is True
    assert get_attr(evaluation, "investigation_sufficient") is True
    assert get_attr(evaluation, "tool_efficient") is True
    assert get_attr(evaluation, "behavioral_slo_pass") is False


def test_strong_observed_evidence_passes_behavioral_slo() -> None:
    trace = make_trace(strong_evidence_tool_calls())

    evaluation = evaluate_trace(trace, expected_outcome())

    assert get_attr(evaluation, "grounded") is True
    assert get_attr(evaluation, "investigation_sufficient") is True
    assert get_attr(evaluation, "tool_efficient") is True
    assert get_attr(evaluation, "behavioral_slo_pass") is True


def test_checkout_sufficiency_requires_distinguishing_payments_symptoms() -> None:
    trace = make_trace(
        [
            make_tool_call(
                1,
                "get_service_health",
                {
                    "service": "checkout",
                    "status": "degraded",
                    "symptoms": ["db_wait", "request_queueing"],
                },
                {"service": "checkout"},
            ),
            make_tool_call(
                2,
                "get_dependencies",
                {
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
                    "service": "postgres",
                    "metric_name": "active_connections",
                    "metrics": [{"name": "db.connections.active", "points": [{"value": 100}]}],
                    "interpretation": "postgres connection pool saturated at 100 of 100",
                },
                {"service": "postgres", "metric_name": "active_connections"},
            ),
            make_tool_call(
                4,
                "get_recent_changes",
                {
                    "service": "checkout",
                    "changes": [
                        {
                            "component": "database_pool",
                            "field": "max_open_connections",
                            "from": 20,
                            "to": 80,
                        }
                    ],
                },
                {"service": "checkout"},
            ),
        ],
    )

    evaluation = evaluate_trace(trace, expected_outcome())

    assert get_attr(evaluation, "rca_correct") is True
    assert get_attr(evaluation, "grounded") is True
    assert get_attr(evaluation, "investigation_sufficient") is False
    assert get_attr(evaluation, "behavioral_slo_pass") is False


def test_conclusive_incident_with_inconclusive_rca_fails_behavioral_slo() -> None:
    trace = make_trace(
        strong_evidence_tool_calls(),
        final_root_cause="Insufficient evidence to determine a single root cause.",
    )

    evaluation = evaluate_trace(trace, expected_outcome())

    assert get_attr(evaluation, "rca_correct") is False
    assert get_attr(evaluation, "behavioral_slo_pass") is False


def test_inconclusive_scenario_fails_when_agent_overclaims_precise_root_cause() -> None:
    trace = make_trace(
        [
            make_tool_call(
                1,
                "get_service_health",
                {"service": "frontend", "status": "degraded", "signals": ["HTTP 500 spike"]},
                {"service": "frontend"},
            ),
            make_tool_call(
                2,
                "search_logs",
                {
                    "service": "frontend",
                    "matches": [{"message": "product page render failed after cache miss"}],
                },
                {"service": "frontend"},
            ),
            make_tool_call(
                3,
                "get_dependencies",
                {"service": "frontend", "dependencies": ["checkout"]},
                {"service": "frontend"},
            ),
            make_tool_call(
                4,
                "get_recent_changes",
                {"service": "frontend", "changes": []},
                {"service": "frontend"},
            ),
        ],
        final_root_cause="Frontend product errors were caused by a checkout outage.",
    )

    evaluation = evaluate_trace(
        trace,
        expected_outcome("Insufficient evidence to determine a single root cause for the frontend product page errors."),
    )

    assert get_attr(evaluation, "rca_correct") is False
    assert get_attr(evaluation, "behavioral_slo_pass") is False


def test_duplicate_tool_call_fails_efficiency_only() -> None:
    calls = strong_evidence_tool_calls()
    duplicate = make_tool_call(
        7,
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
    reordered = [calls[index] for index in (3, 0, 5, 4, 2, 1)]
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


def test_expected_outcome_changes_rca_accuracy_and_composite_slo_only() -> None:
    trace = make_trace(strong_evidence_tool_calls())

    matching = evaluate_trace(trace, expected_outcome())
    different = evaluate_trace(
        trace,
        expected_outcome("Payments failed because an external gateway timed out."),
    )

    assert get_attr(matching, "rca_correct") is True
    assert get_attr(different, "rca_correct") is False
    behavioral_fields = ("grounded", "investigation_sufficient", "tool_efficient")
    assert all(
        get_attr(matching, field) == get_attr(different, field)
        for field in behavioral_fields
    )
    assert get_attr(matching, "behavioral_slo_pass") is True
    assert get_attr(different, "behavioral_slo_pass") is False


def test_unknown_tool_fails_efficiency_only() -> None:
    calls = strong_evidence_tool_calls()
    calls.append(
        make_tool_call(
            7,
            "query_customer_sentiment",
            {"summary": "Customers report slow checkout."},
            {"service": "checkout"},
        )
    )

    evaluation = evaluate_trace(make_trace(calls), expected_outcome())

    assert get_attr(evaluation, "grounded") is True
    assert get_attr(evaluation, "investigation_sufficient") is True
    assert get_attr(evaluation, "tool_efficient") is False
    assert get_attr(evaluation, "behavioral_slo_pass") is False
    assert "unknown tools" in " ".join(get_attr(evaluation, "reasons")).lower()


def test_irrelevant_known_tool_call_fails_efficiency_only() -> None:
    calls = strong_evidence_tool_calls()
    calls.append(
        make_tool_call(
            7,
            "get_service_health",
            {"service": "catalog", "status": "healthy"},
            {"service": "catalog"},
        )
    )

    evaluation = evaluate_trace(make_trace(calls), expected_outcome())

    assert get_attr(evaluation, "grounded") is True
    assert get_attr(evaluation, "investigation_sufficient") is True
    assert get_attr(evaluation, "tool_efficient") is False
    assert get_attr(evaluation, "behavioral_slo_pass") is False
    assert "irrelevant service queries: catalog" in " ".join(
        get_attr(evaluation, "reasons")
    ).lower()


def test_excessive_calls_fail_efficiency_only() -> None:
    calls = strong_evidence_tool_calls()
    for sequence in range(7, 10):
        calls.append(
            make_tool_call(
                sequence,
                "search_logs",
                {"matches": []},
                {"service": f"unrelated-{sequence}"},
            )
        )

    evaluation = evaluate_trace(make_trace(calls), expected_outcome())

    assert get_attr(evaluation, "grounded") is True
    assert get_attr(evaluation, "investigation_sufficient") is True
    assert get_attr(evaluation, "tool_efficient") is False
    assert get_attr(evaluation, "behavioral_slo_pass") is False
    assert "9 calls exceeds the 8-call budget" in " ".join(
        get_attr(evaluation, "reasons")
    )


def test_reasons_name_claimed_concepts_and_evidence_families() -> None:
    evaluation = evaluate_trace(
        make_trace(strong_evidence_tool_calls()),
        expected_outcome(),
    )

    reasons = " ".join(get_attr(evaluation, "reasons")).lower()
    assert "postgres" in reasons
    assert "connection_exhaustion" in reasons
    assert "runtime_signal" in reasons
    assert "topology" in reasons
    assert "change" in reasons
