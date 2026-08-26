from __future__ import annotations

import time
from typing import Any

import pytest
from conftest import (
    checkout_provider,
    dump_model,
    fake_provider,
    import_model,
    make_trace,
    provider_result,
    recovery_provider,
    strong_evidence_tool_calls,
    validate_model,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

INTERNAL_SCENARIO_ID = "checkout_db_pool_exhaustion"
PUBLIC_SCENARIO_ID = "checkout_latency_spike"
INCIDENT_ID = "inc_checkout_001"


def _pending_run(repo: Any) -> str:
    replay_instance_id = repo.create_replay_instance(PUBLIC_SCENARIO_ID)
    return repo.create_pending_run(PUBLIC_SCENARIO_ID, replay_instance_id, "candidate")


def _completed_run(repo: Any) -> str:
    replay_instance_id = repo.create_replay_instance(PUBLIC_SCENARIO_ID)
    trace = make_trace(strong_evidence_tool_calls()).model_copy(
        update={"incident_id": INCIDENT_ID}
    )
    return repo.persist_run(INTERNAL_SCENARIO_ID, replay_instance_id, trace, None)


def _wait_for_completed(client: TestClient, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/investigations/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] == "completed":
            return payload
        if payload["status"] == "failed":
            raise AssertionError(payload["error"])
        time.sleep(0.01)
    raise AssertionError(f"Investigation {run_id} did not complete")


def test_history_is_empty_and_get_has_no_model_or_database_side_effects() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    provider = checkout_provider()
    api.set_model_provider_factory(lambda: provider)
    repo = ReplayRepository()
    client = TestClient(api.app)

    before = {
        table: repo._one(f"SELECT COUNT(*) AS count FROM {table}")["count"]
        for table in ("investigation_runs", "replay_instances", "investigation_events")
    }
    response = client.get("/investigations")
    after = {
        table: repo._one(f"SELECT COUNT(*) AS count FROM {table}")["count"]
        for table in ("investigation_runs", "replay_instances", "investigation_events")
    }

    assert response.status_code == 200
    assert response.json() == []
    assert before == after
    assert provider.requests == []


def test_history_is_newest_first_strict_public_and_has_completed_outcome() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    repo = ReplayRepository()
    older_run_id = _completed_run(repo)
    newer_run_id = _pending_run(repo)
    with repo.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE investigation_runs SET created_at = :created_at, "
                "updated_at = :updated_at WHERE id = :run_id"
            ),
            [
                {
                    "run_id": older_run_id,
                    "created_at": "2026-08-26T10:00:00+00:00",
                    "updated_at": "2026-08-26T10:01:00+00:00",
                },
                {
                    "run_id": newer_run_id,
                    "created_at": "2026-08-26T11:00:00+00:00",
                    "updated_at": "2026-08-26T11:00:00+00:00",
                },
            ],
        )

    response = TestClient(api.app).get("/investigations")
    summaries = response.json()

    assert response.status_code == 200
    assert [summary["run_id"] for summary in summaries] == [newer_run_id, older_run_id]
    assert set(summaries[0]) == {
        "run_id",
        "scenario_id",
        "incident_id",
        "incident_title",
        "status",
        "outcome",
        "created_at",
        "updated_at",
    }
    assert summaries[0] == {
        "run_id": newer_run_id,
        "scenario_id": PUBLIC_SCENARIO_ID,
        "incident_id": INCIDENT_ID,
        "incident_title": "Checkout latency and errors during payment submit",
        "status": "queued",
        "outcome": None,
        "created_at": "2026-08-26T11:00:00+00:00",
        "updated_at": "2026-08-26T11:00:00+00:00",
    }
    assert summaries[1]["status"] == "completed"
    assert summaries[1]["outcome"] == "root_cause"
    assert INTERNAL_SCENARIO_ID not in repr(summaries)
    assert not ({"trace", "evaluation", "evidence", "error"} & set(summaries[1]))


def test_history_summarizes_queued_running_and_failed_without_outcomes() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    repo = ReplayRepository()
    queued_run_id = _pending_run(repo)
    running_run_id = _pending_run(repo)
    failed_run_id = _pending_run(repo)
    assert repo.claim_run(
        running_run_id,
        {
            "scenario_id": PUBLIC_SCENARIO_ID,
            "incident_id": INCIDENT_ID,
            "agent_config_id": "candidate",
        },
    )
    assert repo.fail_run(failed_run_id, "Provider unavailable.")

    summaries = TestClient(api.app).get("/investigations").json()
    by_id = {summary["run_id"]: summary for summary in summaries}

    assert by_id[queued_run_id]["status"] == "queued"
    assert by_id[running_run_id]["status"] == "running"
    assert by_id[failed_run_id]["status"] == "failed"
    assert all(by_id[run_id]["outcome"] is None for run_id in by_id)
    assert all("error" not in summary for summary in summaries)


def test_history_is_capped_at_latest_50_runs() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    repo = ReplayRepository()
    run_ids = [_pending_run(repo) for _ in range(51)]

    summaries = TestClient(api.app).get("/investigations").json()

    assert len(summaries) == 50
    assert [summary["run_id"] for summary in summaries] == list(reversed(run_ids[1:]))
    assert run_ids[0] not in {summary["run_id"] for summary in summaries}


def test_history_excludes_comparison_arms_but_keeps_responder_runs() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    InvestigationResponse = import_model("InvestigationResponse")
    repo = ReplayRepository()
    responder_run_id = _completed_run(repo)
    baseline_run_id = _completed_run(repo)
    candidate_run_id = _completed_run(repo)
    repo.persist_comparison(
        INTERNAL_SCENARIO_ID,
        InvestigationResponse(
            run_id=baseline_run_id,
            trace=repo.get_run(baseline_run_id),
            evaluation=None,
        ),
        InvestigationResponse(
            run_id=candidate_run_id,
            trace=repo.get_run(candidate_run_id),
            evaluation=None,
        ),
    )

    summaries = TestClient(api.app).get("/investigations").json()

    assert [summary["run_id"] for summary in summaries] == [responder_run_id]
    assert summaries[0]["outcome"] == "root_cause"


def test_completed_run_get_reloads_follow_ups_and_executed_action_read_only() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    investigation_provider = checkout_provider(action=True)
    chat_provider = fake_provider(
        [
            provider_result(
                response_id="history-chat",
                final={
                    "message": "Payments errors were collateral to checkout waiting on its database.",
                    "evidence_ids": ["log_payments_upstream_cancelled"],
                    "action_proposal": None,
                },
            )
        ]
    )
    providers = [investigation_provider, chat_provider, recovery_provider()]
    provider_factory_calls = 0

    def provider_factory() -> Any:
        nonlocal provider_factory_calls
        provider_factory_calls += 1
        return providers.pop(0)

    api.set_model_provider_factory(provider_factory)
    client = TestClient(api.app)
    accepted = client.post(
        "/investigations",
        json={"scenario_id": PUBLIC_SCENARIO_ID, "mode": "candidate"},
    ).json()
    completed = _wait_for_completed(client, accepted["run_id"])
    proposal_id = completed["response"]["trace"]["final_result"]["action_proposal"][
        "id"
    ]
    question = "Why is payments not the initiating cause?"
    chat = client.post(
        f"/investigations/{accepted['run_id']}/messages",
        json={"message": question},
    )
    confirmed = client.post(
        f"/investigations/{accepted['run_id']}/actions/{proposal_id}/confirm"
    )
    assert chat.status_code == 200
    assert confirmed.status_code == 200

    repo = ReplayRepository()
    replay_instance_id = repo.get_run_replay_instance_id(accepted["run_id"])
    before = {
        "provider_factory_calls": provider_factory_calls,
        "replay_state": repo.get_replay_state(replay_instance_id),
        "chat_rows": repo._one(
            "SELECT COUNT(*) AS count FROM chat_messages WHERE run_id = :run_id",
            run_id=accepted["run_id"],
        )["count"],
        "event_rows": repo._one(
            "SELECT COUNT(*) AS count FROM investigation_events WHERE run_id = :run_id",
            run_id=accepted["run_id"],
        )["count"],
    }

    reopened = client.get(f"/investigations/{accepted['run_id']}")

    after = {
        "provider_factory_calls": provider_factory_calls,
        "replay_state": repo.get_replay_state(replay_instance_id),
        "chat_rows": repo._one(
            "SELECT COUNT(*) AS count FROM chat_messages WHERE run_id = :run_id",
            run_id=accepted["run_id"],
        )["count"],
        "event_rows": repo._one(
            "SELECT COUNT(*) AS count FROM investigation_events WHERE run_id = :run_id",
            run_id=accepted["run_id"],
        )["count"],
    }
    payload = reopened.json()

    assert reopened.status_code == 200
    assert payload["status"] == "completed"
    assert payload["follow_ups"] == [
        {
            "question": question,
            "response": chat.json(),
        }
    ]
    assert payload["action_result"] == confirmed.json()
    assert payload["action_result"]["proposal"]["status"] == "executed"
    assert payload["action_result"]["verification_status"] == "verified"
    assert before == after
    assert providers == []


def test_completed_run_get_keeps_unconfirmed_proposal_pending() -> None:
    from reliable_incident_agent import api

    provider = checkout_provider(action=True)
    api.set_model_provider_factory(lambda: provider)
    client = TestClient(api.app)
    accepted = client.post(
        "/investigations",
        json={"scenario_id": PUBLIC_SCENARIO_ID, "mode": "candidate"},
    ).json()

    payload = _wait_for_completed(client, accepted["run_id"])
    request_count = len(provider.requests)
    reopened = client.get(f"/investigations/{accepted['run_id']}").json()

    assert payload["action_result"] is None
    assert reopened["action_result"] is None
    assert reopened["follow_ups"] == []
    assert reopened["response"]["trace"]["final_result"]["action_proposal"][
        "status"
    ] == "proposed"
    assert len(provider.requests) == request_count


def test_investigation_summary_model_forbids_hidden_fields_and_invalid_outcomes() -> None:
    InvestigationSummary = import_model("InvestigationSummary")
    payload = {
        "run_id": "run-1",
        "scenario_id": PUBLIC_SCENARIO_ID,
        "incident_id": INCIDENT_ID,
        "incident_title": "Checkout latency and errors during payment submit",
        "status": "completed",
        "outcome": "root_cause",
        "created_at": "2026-08-26T10:00:00+00:00",
        "updated_at": "2026-08-26T10:01:00+00:00",
    }

    summary = validate_model(InvestigationSummary, payload)
    assert dump_model(summary) == payload

    with pytest.raises(ValidationError):
        validate_model(InvestigationSummary, payload | {"trace": {}})
    with pytest.raises(ValidationError):
        validate_model(
            InvestigationSummary,
            payload | {"status": "running", "outcome": "root_cause"},
        )


def test_scenarios_expose_source_backed_agent_safe_target_slis() -> None:
    from reliable_incident_agent import api

    client = TestClient(api.app)
    expected = {
        "checkout_latency_spike": "Checkout POST /checkout p95 latency below 500 ms.",
        "payment_submission_failures": "Payment authorization error rate below 1 percent.",
        "frontend_error_spike": "Product detail page HTTP 5xx rate below 1 error per minute.",
    }

    scenarios = client.get("/scenarios").json()

    assert {scenario["id"]: scenario["target_sli"] for scenario in scenarios} == expected
    for scenario in scenarios:
        detail = client.get(f"/scenarios/{scenario['id']}").json()
        assert detail["incident"]["target_sli"] == expected[scenario["id"]]
    assert not any(
        term in repr(expected).lower()
        for term in ("exhaustion", "pool", "gateway timeout", "expected outcome")
    )
