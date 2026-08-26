from __future__ import annotations

from conftest import (
    EXPECTED_RCA,
    evaluate_trace,
    expected_outcome,
    get_attr,
    import_module,
    run_investigation,
)


def test_weak_and_reliable_investigations_return_same_expected_rca() -> None:
    weak = run_investigation("weak")
    reliable = run_investigation("reliable")

    assert get_attr(weak, "trace.final_root_cause") == EXPECTED_RCA
    assert get_attr(reliable, "trace.final_root_cause") == EXPECTED_RCA


def test_weak_investigation_is_correct_but_fails_behavioral_slo() -> None:
    weak = run_investigation("weak")

    assert get_attr(weak, "evaluation.rca_correct") is True
    assert get_attr(weak, "evaluation.behavioral_slo_pass") is False
    assert (
        get_attr(weak, "evaluation.grounded") is False
        or get_attr(weak, "evaluation.investigation_sufficient") is False
    )
    assert get_attr(weak, "evaluation.tool_efficient") is True


def test_reliable_investigation_passes_behavioral_slo() -> None:
    reliable = run_investigation("reliable")

    assert get_attr(reliable, "evaluation.rca_correct") is True
    assert get_attr(reliable, "evaluation.grounded") is True
    assert get_attr(reliable, "evaluation.investigation_sufficient") is True
    assert get_attr(reliable, "evaluation.tool_efficient") is True
    assert get_attr(reliable, "evaluation.behavioral_slo_pass") is True


def test_payments_gateway_scenario_uses_different_valid_path() -> None:
    db = import_module("db")
    db.init_db()
    replay = import_module("replay")
    investigator = import_module("investigator")
    repo = replay.ReplayRepository()
    trace = investigator.run_investigation("payments_gateway_timeout", "reliable", repo)
    evaluation = evaluate_trace(trace, repo.get_expected_outcome("payments_gateway_timeout"))

    tool_names = [call.tool_name for call in trace.tool_calls]
    tool_services = [call.arguments.get("service") for call in trace.tool_calls]
    assert "payments" in tool_services
    assert "get_metrics" in tool_names
    assert "get_recent_changes" in tool_names
    assert evaluation.rca_correct is True
    assert evaluation.behavioral_slo_pass is True


def test_insufficient_evidence_scenario_avoids_overclaiming() -> None:
    db = import_module("db")
    db.init_db()
    replay = import_module("replay")
    investigator = import_module("investigator")
    repo = replay.ReplayRepository()
    trace = investigator.run_investigation("insufficient_frontend_evidence", "reliable", repo)
    evaluation = evaluate_trace(
        trace,
        expected_outcome("Insufficient evidence to determine a single root cause for the frontend product page errors."),
    )

    assert "Insufficient evidence" in trace.final_root_cause
    assert evaluation.rca_correct is True
    assert evaluation.behavioral_slo_pass is True
