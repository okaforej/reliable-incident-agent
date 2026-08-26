"""CLI demo for baseline vs candidate investigation comparison."""

from __future__ import annotations

import argparse
import os
from typing import Any

from rich.console import Console
from rich.table import Table

from reliable_incident_agent.db import init_db
from reliable_incident_agent.evaluator import evaluate_trace
from reliable_incident_agent.investigator import run_investigation
from reliable_incident_agent.providers import (
    FakeModelProvider,
    ProviderResult,
    ProviderToolCall,
)
from reliable_incident_agent.replay import ReplayRepository

SCENARIO_ID = "checkout_latency_spike"
EXPECTED_RCA = (
    "Checkout latency was caused by postgres connection exhaustion after checkout "
    "deployed a database pool max_open_connections change from 20 to 80."
)


def main() -> None:
    args = _parse_args()
    init_db()
    repo = ReplayRepository()
    expected = repo.get_expected_outcome(SCENARIO_ID)

    if args.live:
        if not os.getenv("OPENAI_API_KEY"):
            raise SystemExit("OPENAI_API_KEY is required for --live.")
        baseline_provider = None
        candidate_provider = None
        provider_label = "Live OpenAI Responses API"
    else:
        baseline_provider = _recorded_baseline_provider()
        candidate_provider = _recorded_candidate_provider()
        provider_label = "Recorded fake-provider contract demo"

    baseline_trace = run_investigation(
        SCENARIO_ID,
        "baseline",
        repo,
        provider=baseline_provider,
    )
    candidate_trace = run_investigation(
        SCENARIO_ID,
        "candidate",
        repo,
        provider=candidate_provider,
    )
    baseline_eval = evaluate_trace(baseline_trace, expected)
    candidate_eval = evaluate_trace(candidate_trace, expected)

    console = Console()
    console.print(f"[bold]Provider path:[/bold] {provider_label}")
    console.print("[bold]Output metric[/bold]")
    console.print(f"Baseline RCA accuracy: {_status(baseline_eval.rca_correct)}")
    console.print(f"Candidate RCA accuracy: {_status(candidate_eval.rca_correct)}")
    console.print("\n[bold]Final RCA / abstention results[/bold]")
    console.print(f"Baseline: {baseline_trace.final_root_cause}")
    console.print(f"Candidate: {candidate_trace.final_root_cause}")
    console.print("\nUse the Behavioral SLO rows to inspect how each configuration investigated.")

    table = Table(title="Behavioral SLO Results")
    table.add_column("Metric")
    table.add_column("Baseline")
    table.add_column("Candidate")
    rows = [
        ("Grounded investigation", baseline_eval.grounded, candidate_eval.grounded),
        (
            "Investigation sufficiency",
            baseline_eval.investigation_sufficient,
            candidate_eval.investigation_sufficient,
        ),
        ("Tool efficiency", baseline_eval.tool_efficient, candidate_eval.tool_efficient),
        ("Behavioral SLO", baseline_eval.behavioral_slo_pass, candidate_eval.behavioral_slo_pass),
    ]
    for label, baseline_value, candidate_value in rows:
        table.add_row(label, _status(baseline_value), _status(candidate_value))

    console.print(table)
    console.print("\n[bold]Baseline trajectory[/bold]")
    _print_trajectory(console, baseline_trace.tool_calls)
    console.print("\n[bold]Candidate trajectory[/bold]")
    _print_trajectory(console, candidate_trace.tool_calls)
    console.print("\n[bold]Evaluator reasons[/bold]")
    console.print("Baseline:")
    for reason in baseline_eval.reasons:
        console.print(f"- {reason}")
    console.print("Candidate:")
    for reason in candidate_eval.reasons:
        console.print(f"- {reason}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the configured OpenAI provider instead of the recorded fake provider.",
    )
    return parser.parse_args()


def _recorded_baseline_provider() -> FakeModelProvider:
    return FakeModelProvider(
        [
            ProviderResult(
                response_id="baseline-tools-1",
                tool_calls=[
                    ProviderToolCall(
                        name="get_service_health",
                        arguments={"service": "checkout"},
                        call_id="baseline-call-1",
                        purpose="Check the affected service health.",
                    ),
                    ProviderToolCall(
                        name="get_dependencies",
                        arguments={"service": "checkout"},
                        call_id="baseline-call-2",
                        purpose="Find dependencies that could explain checkout latency.",
                    ),
                ],
            ),
            ProviderResult(
                response_id="baseline-tools-2",
                tool_calls=[
                    ProviderToolCall(
                        name="get_metrics",
                        arguments={"service": "postgres", "metric_name": "db.connections.active"},
                        call_id="baseline-call-3",
                        purpose="Test whether the database dependency is saturated.",
                    ),
                    ProviderToolCall(
                        name="get_recent_changes",
                        arguments={"service": "checkout"},
                        call_id="baseline-call-4",
                        purpose="Check whether checkout recently changed database connection behavior.",
                    ),
                    ProviderToolCall(
                        name="search_logs",
                        arguments={"service": "checkout", "query": "db acquire timeout"},
                        call_id="baseline-call-5",
                        purpose="Look for checkout database wait symptoms.",
                    ),
                    ProviderToolCall(
                        name="search_logs",
                        arguments={"service": "payments", "query": "cancelled"},
                        call_id="baseline-call-6",
                        purpose="Check whether payments is cause or collateral impact.",
                    ),
                ],
            ),
            ProviderResult(response_id="baseline-final", final=_final_result()),
        ]
    )


def _recorded_candidate_provider() -> FakeModelProvider:
    return FakeModelProvider(
        [
            ProviderResult(
                response_id="candidate-tools-1",
                tool_calls=[
                    ProviderToolCall(
                        name="get_metrics",
                        arguments={"service": "postgres", "metric_name": "db.connections.active"},
                        call_id="candidate-call-1",
                        purpose="Check database saturation.",
                    ),
                    ProviderToolCall(
                        name="get_recent_changes",
                        arguments={"service": "checkout"},
                        call_id="candidate-call-2",
                        purpose="Check checkout changes.",
                    ),
                    ProviderToolCall(
                        name="search_logs",
                        arguments={"service": "checkout", "query": "db acquire timeout"},
                        call_id="candidate-call-3",
                        purpose="Find direct checkout timeout logs.",
                    ),
                ],
            ),
            ProviderResult(response_id="candidate-final", final=_final_result()),
        ]
    )


def _final_result() -> dict[str, Any]:
    return {
        "outcome": "root_cause",
        "root_cause": EXPECTED_RCA,
        "confidence": "high",
        "evidence_ids": [
            "metric_postgres_connections",
            "chg_checkout_pool_80",
            "log_checkout_pool_wait_timeout",
        ],
        "hypothesis_summary": [
            {
                "hypothesis": "Postgres connection saturation caused checkout latency.",
                "status": "supported",
                "evidence_ids": ["metric_postgres_connections", "log_checkout_pool_wait_timeout"],
            },
            {
                "hypothesis": "A checkout deployment changed database pool behavior.",
                "status": "supported",
                "evidence_ids": ["chg_checkout_pool_80"],
            },
        ],
        "mitigation": "Rollback checkout db.max_open_connections to 20.",
        "verification_plan": [
            "Verify checkout latency returns to baseline.",
            "Verify postgres active connections fall below threshold.",
        ],
        "missing_evidence": [],
        "action_proposal": None,
    }


def _print_trajectory(console: Console, tool_calls: list[Any]) -> None:
    for call in tool_calls:
        console.print(f"{call.sequence}. {call.tool_name} {call.arguments}")


def _status(value: bool) -> str:
    return "[green]PASS[/green]" if value else "[red]FAIL[/red]"


if __name__ == "__main__":
    main()
