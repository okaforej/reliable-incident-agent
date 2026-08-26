"""CLI demo for baseline vs candidate investigation comparison."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from reliable_incident_agent.db import init_db
from reliable_incident_agent.evaluator import evaluate_trace
from reliable_incident_agent.investigator import run_investigation
from reliable_incident_agent.replay import ReplayRepository

SCENARIO_ID = "checkout_db_pool_exhaustion"


def main() -> None:
    init_db()
    repo = ReplayRepository()
    expected = repo.get_expected_outcome(SCENARIO_ID)
    baseline_trace = run_investigation(SCENARIO_ID, "baseline", repo)
    candidate_trace = run_investigation(SCENARIO_ID, "candidate", repo)
    baseline_eval = evaluate_trace(baseline_trace, expected)
    candidate_eval = evaluate_trace(candidate_trace, expected)

    table = Table(title="Reliable Incident Agent: Output Accuracy Hid a Regression")
    table.add_column("Metric")
    table.add_column("Baseline")
    table.add_column("Candidate")
    rows = [
        ("RCA accuracy", baseline_eval.rca_correct, candidate_eval.rca_correct),
        ("Grounded investigation", baseline_eval.grounded, candidate_eval.grounded),
        ("Investigation sufficiency", baseline_eval.investigation_sufficient, candidate_eval.investigation_sufficient),
        ("Tool efficiency", baseline_eval.tool_efficient, candidate_eval.tool_efficient),
        ("Behavioral SLO", baseline_eval.behavioral_slo_pass, candidate_eval.behavioral_slo_pass),
    ]
    for label, baseline_value, candidate_value in rows:
        table.add_row(label, _status(baseline_value), _status(candidate_value))

    console = Console()
    console.print(table)
    console.print("\n[bold]Final RCA[/bold]")
    console.print(baseline_trace.final_root_cause)
    console.print("\n[bold]Baseline evaluator reasons[/bold]")
    for reason in baseline_eval.reasons:
        console.print(f"- {reason}")
    console.print("\n[bold]Candidate evaluator reasons[/bold]")
    for reason in candidate_eval.reasons:
        console.print(f"- {reason}")


def _status(value: bool) -> str:
    return "[green]PASS[/green]" if value else "[red]FAIL[/red]"


if __name__ == "__main__":
    main()
