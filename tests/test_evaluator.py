from __future__ import annotations

import unittest
from typing import Any

from evaluation import evaluate_trace
from shared.models import InvestigationTrace, ToolCall


EXPECTED_POSTGRES = "Postgres connection exhaustion."


def tool_call(
    sequence: int,
    tool_name: str,
    result: dict[str, Any],
    service: str = "checkout",
    **arguments: Any,
) -> ToolCall:
    return ToolCall(
        sequence=sequence,
        tool_name=tool_name,
        arguments={"service": service, **arguments},
        result=result,
    )


def trace(
    calls: list[ToolCall],
    final_root_cause: str = EXPECTED_POSTGRES,
    expected_root_cause: str = EXPECTED_POSTGRES,
) -> InvestigationTrace:
    return InvestigationTrace(
        incident_id="checkout-latency",
        incident_description="Checkout latency increased after a deployment.",
        expected_root_cause=expected_root_cause,
        tool_calls=calls,
        final_root_cause=final_root_cause,
    )


def strong_calls() -> list[ToolCall]:
    return [
        tool_call(
            1,
            "search_logs",
            {"matches": [{"message": "postgres connection pool exhausted"}]},
        ),
        tool_call(
            2,
            "get_dependencies",
            {"dependencies": [{"service": "postgres", "role": "database"}]},
        ),
        tool_call(
            3,
            "get_service_health",
            {"status": "critical", "summary": "connection pool saturation"},
            service="postgres",
        ),
    ]


class EvaluateTraceTests(unittest.TestCase):
    def test_correct_rca_with_good_trajectory_passes(self) -> None:
        result = evaluate_trace(trace(strong_calls()))

        self.assertTrue(result.rca_correct)
        self.assertTrue(result.grounded)
        self.assertTrue(result.investigation_sufficient)
        self.assertTrue(result.tool_efficient)
        self.assertTrue(result.behavioral_slo_pass)

    def test_same_correct_rca_with_lucky_trajectory_fails(self) -> None:
        calls = [
            tool_call(
                1,
                "search_logs",
                {"matches": [{"message": "postgres connection pool exhausted"}]},
            )
        ]

        result = evaluate_trace(trace(calls))

        self.assertTrue(result.rca_correct)
        self.assertTrue(result.grounded)
        self.assertFalse(result.investigation_sufficient)
        self.assertFalse(result.behavioral_slo_pass)

    def test_incorrect_rca_is_separate_from_supported_behavior(self) -> None:
        result = evaluate_trace(
            trace(
                strong_calls(),
                expected_root_cause="Payments service dependency failures.",
            )
        )

        self.assertFalse(result.rca_correct)
        self.assertTrue(result.behavioral_slo_pass)

    def test_redundant_exact_call_fails_efficiency(self) -> None:
        calls = strong_calls()
        calls.append(
            tool_call(
                4,
                "search_logs",
                {"matches": [{"message": "postgres connection pool exhausted"}]},
            )
        )

        result = evaluate_trace(trace(calls))

        self.assertFalse(result.tool_efficient)
        self.assertIn("duplicate", result.reasons[-1])

    def test_explicitly_irrelevant_call_fails_efficiency(self) -> None:
        calls = strong_calls()
        calls.append(
            tool_call(
                4,
                "get_service_health",
                {"status": "healthy", "relevant": False},
                service="unrelated-cache",
            )
        )

        result = evaluate_trace(trace(calls))

        self.assertFalse(result.tool_efficient)
        self.assertIn("irrelevant", result.reasons[-1])

    def test_missing_supporting_evidence_fails_grounding(self) -> None:
        calls = [
            tool_call(
                1,
                "search_logs",
                {"matches": [{"message": "request completed slowly"}]},
            ),
            tool_call(
                2,
                "get_dependencies",
                {"dependencies": [{"service": "catalog"}]},
            ),
            tool_call(
                3,
                "get_service_health",
                {"status": "degraded", "summary": "high latency"},
            ),
        ]

        result = evaluate_trace(trace(calls))

        self.assertFalse(result.grounded)
        self.assertFalse(result.behavioral_slo_pass)

    def test_failed_tool_does_not_count_as_informative(self) -> None:
        calls = strong_calls()[:2]
        calls.append(
            tool_call(
                3,
                "get_service_health",
                {"status": "unknown", "error": "tool timed out"},
                service="postgres",
            )
        )

        result = evaluate_trace(trace(calls))

        self.assertFalse(result.investigation_sufficient)

    def test_alternative_valid_path_can_pass_without_dependencies(self) -> None:
        calls = [
            tool_call(
                1,
                "get_service_health",
                {"status": "critical", "summary": "connection pool saturation"},
                service="postgres",
            ),
            tool_call(
                2,
                "search_logs",
                {"matches": [{"message": "postgres db timeout"}]},
            ),
            tool_call(
                3,
                "get_recent_changes",
                {"changes": [{"summary": "database pool configuration change"}]},
            ),
        ]

        result = evaluate_trace(trace(calls))

        self.assertTrue(result.behavioral_slo_pass)


if __name__ == "__main__":
    unittest.main()