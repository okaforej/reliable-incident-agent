from __future__ import annotations

from conftest import (
    EXPECTED_RCA,
    evaluate_trace,
    expected_outcome,
    get_attr,
    import_module,
    run_investigation,
)


def test_baseline_and_candidate_investigations_return_same_expected_rca() -> None:
    candidate = run_investigation("candidate")
    baseline = run_investigation("baseline")

    assert get_attr(candidate, "trace.final_root_cause") == EXPECTED_RCA
    assert get_attr(baseline, "trace.final_root_cause") == EXPECTED_RCA


def test_candidate_investigation_is_correct_but_fails_behavioral_slo() -> None:
    candidate = run_investigation("candidate")

    assert get_attr(candidate, "evaluation.rca_correct") is True
    assert get_attr(candidate, "evaluation.grounded") is False
    assert get_attr(candidate, "evaluation.investigation_sufficient") is False
    assert get_attr(candidate, "evaluation.tool_efficient") is True
    assert get_attr(candidate, "evaluation.behavioral_slo_pass") is False


def test_baseline_investigation_passes_behavioral_slo() -> None:
    baseline = run_investigation("baseline")

    assert get_attr(baseline, "evaluation.rca_correct") is True
    assert get_attr(baseline, "evaluation.grounded") is True
    assert get_attr(baseline, "evaluation.investigation_sufficient") is True
    assert get_attr(baseline, "evaluation.tool_efficient") is True
    assert get_attr(baseline, "evaluation.behavioral_slo_pass") is True


def test_payments_gateway_scenario_uses_different_valid_path() -> None:
    db = import_module("db")
    db.init_db()
    replay = import_module("replay")
    investigator = import_module("investigator")
    repo = replay.ReplayRepository()
    trace = investigator.run_investigation("payments_gateway_timeout", "baseline", repo)
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
    trace = investigator.run_investigation("insufficient_frontend_evidence", "baseline", repo)
    evaluation = evaluate_trace(
        trace,
        expected_outcome("Insufficient evidence to determine a single root cause for the frontend product page errors."),
    )

    assert "Insufficient evidence" in trace.final_root_cause
    assert evaluation.rca_correct is True
    assert evaluation.behavioral_slo_pass is True


def test_seeded_candidate_does_not_receive_credit_for_unobserved_replay_evidence() -> None:
    db = import_module("db")
    db.init_db()
    replay = import_module("replay")
    investigator = import_module("investigator")
    repo = replay.ReplayRepository()
    trace = investigator.run_investigation("checkout_db_pool_exhaustion", "candidate", repo)
    evaluation = evaluate_trace(trace, repo.get_expected_outcome("checkout_db_pool_exhaustion"))

    observed_tools = {call.tool_name for call in trace.tool_calls}
    assert "get_metrics" not in observed_tools
    assert "get_recent_changes" not in observed_tools
    assert evaluation.rca_correct is True
    assert evaluation.grounded is False
    assert evaluation.investigation_sufficient is False
