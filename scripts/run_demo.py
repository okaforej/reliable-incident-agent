"""CLI demo for weak vs reliable investigation comparison."""

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
    weak_trace = run_investigation(SCENARIO_ID, "weak", repo)
    reliable_trace = run_investigation(SCENARIO_ID, "reliable", repo)
    weak_eval = evaluate_trace(weak_trace, expected)
    reliable_eval = evaluate_trace(reliable_trace, expected)

    table = Table(title="Reliable Incident Agent: Same RCA, Different Trajectory")
    table.add_column("Metric")
    table.add_column("Weak Agent")
    table.add_column("Reliable Agent")
    rows = [
        ("RCA correct", weak_eval.rca_correct, reliable_eval.rca_correct),
        ("Grounded", weak_eval.grounded, reliable_eval.grounded),
        ("Sufficient", weak_eval.investigation_sufficient, reliable_eval.investigation_sufficient),
        ("Efficient", weak_eval.tool_efficient, reliable_eval.tool_efficient),
        ("Behavioral SLO", weak_eval.behavioral_slo_pass, reliable_eval.behavioral_slo_pass),
    ]
    for label, weak_value, reliable_value in rows:
        table.add_row(label, _status(weak_value), _status(reliable_value))

    console = Console()
    console.print(table)
    console.print("\n[bold]Final RCA[/bold]")
    console.print(reliable_trace.final_root_cause)
    console.print("\n[bold]Weak evaluator reasons[/bold]")
    for reason in weak_eval.reasons:
        console.print(f"- {reason}")
    console.print("\n[bold]Reliable evaluator reasons[/bold]")
    for reason in reliable_eval.reasons:
        console.print(f"- {reason}")


def _status(value: bool) -> str:
    return "[green]PASS[/green]" if value else "[red]FAIL[/red]"


if __name__ == "__main__":
    main()
