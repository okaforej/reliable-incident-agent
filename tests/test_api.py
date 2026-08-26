from __future__ import annotations

import time

import pytest
from conftest import (
    SCENARIO_ID,
    checkout_provider,
    fake_provider,
    provider_result,
    provider_tool_call,
    recovery_provider,
)
from fastapi.testclient import TestClient

PUBLIC_SCENARIO_ID = "checkout_latency_spike"
PUBLIC_FORBIDDEN_TERMS = {
    "checkout_db_pool_exhaustion",
    "db_pool",
    "db pool",
    "pool exhaustion",
    "db pool exhaustion",
    "payments_gateway_timeout",
    "gateway timeout",
    "insufficient_frontend_evidence",
    "insufficient",
    "inconclusive",
    "partial evidence",
    "expected",
}


def _wait_for_terminal(client: TestClient, run_id: str, timeout: float = 3) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/investigations/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"Investigation {run_id} did not terminate within {timeout} seconds")


def _start_completed(
    client: TestClient,
    scenario_id: str = PUBLIC_SCENARIO_ID,
    mode: str = "candidate",
) -> dict[str, object]:
    accepted = client.post(
        "/investigations",
        json={"scenario_id": scenario_id, "mode": mode},
    )
    assert accepted.status_code == 202
    terminal = _wait_for_terminal(client, accepted.json()["run_id"])
    assert terminal["status"] == "completed", terminal
    assert terminal["response"] is not None
    return terminal["response"]


def test_get_requests_do_not_start_model_work() -> None:
    from reliable_incident_agent import api

    provider = checkout_provider()
    api.set_model_provider_factory(lambda: provider)
    client = TestClient(api.app)

    assert client.get("/scenarios").status_code == 200
    assert client.get(f"/scenarios/{PUBLIC_SCENARIO_ID}").status_code == 200

    assert provider.requests == []


def test_health_has_a_strict_openapi_response_contract() -> None:
    from reliable_incident_agent import api

    client = TestClient(api.app)

    response = client.get("/health")
    schema = api.app.openapi()

    assert response.status_code == 200
    assert set(response.json()) == {
        "status",
        "openai_api_key_configured",
        "openai_model",
    }
    assert schema["paths"]["/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/HealthResponse"}


def test_chat_rejects_whitespace_before_run_lookup() -> None:
    from reliable_incident_agent import api

    client = TestClient(api.app)

    response = client.post(
        "/investigations/not-a-run/messages",
        json={"message": "  \n\t "},
    )

    assert response.status_code == 422


def test_public_scenario_fields_are_causal_neutral() -> None:
    from reliable_incident_agent import api

    api.set_model_provider_factory(checkout_provider)
    client = TestClient(api.app)
    scenarios = client.get("/scenarios").json()

    assert {scenario["id"] for scenario in scenarios} == {
        "checkout_latency_spike",
        "payment_submission_failures",
        "frontend_error_spike",
    }
    assert {scenario["name"] for scenario in scenarios} == {
        "Checkout Latency Spike",
        "Payment Submission Failures",
        "Frontend Error Spike",
    }
    serialized = repr(scenarios).lower()
    assert not any(term in serialized for term in PUBLIC_FORBIDDEN_TERMS)

    for scenario in scenarios:
        assert scenario["status"] == "active"
        detail = client.get(f"/scenarios/{scenario['id']}").json()
        assert detail["incident"]["status"] == "active"
        public_text = repr(
            {
                "id": detail["id"],
                "name": detail["name"],
                "incident": detail["incident"],
                "services": detail["services"],
            }
        ).lower()
        assert not any(term in public_text for term in PUBLIC_FORBIDDEN_TERMS)
        assert [service["name"] for service in detail["services"]] == [detail["incident"]["affected_service"]]


def test_investigation_post_runs_fake_provider_and_persists_trace() -> None:
    from reliable_incident_agent import api

    provider = checkout_provider()
    api.set_model_provider_factory(lambda: provider)
    client = TestClient(api.app)

    created = client.post("/investigations", json={"scenario_id": PUBLIC_SCENARIO_ID, "mode": "candidate"})

    assert created.status_code == 202
    assert set(created.json()) == {"run_id", "scenario_id", "status"}
    assert created.json()["scenario_id"] == PUBLIC_SCENARIO_ID
    payload = _wait_for_terminal(client, created.json()["run_id"])["response"]
    assert payload is not None
    assert payload["trace"]["provider_metadata"]["provider"] == "fake"
    assert payload["trace"]["tool_calls"][0]["tool_name"] == "get_service_health"
    assert payload["evaluation"]["rca_correct"] is True
    assert payload["evaluation"]["behavioral_slo_pass"] is True
    assert "expected root cause" not in provider.requests[0]["input_items"][0]["content"].lower()

    fetched = client.get(f"/investigations/{payload['run_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["response"]["trace"]["final_root_cause"] == payload["trace"]["final_root_cause"]


def test_expected_outcome_is_loaded_only_after_trace_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    provider = checkout_provider()
    original = ReplayRepository.get_expected_outcome

    def get_expected_after_model(self: ReplayRepository, scenario_id: str):
        assert provider.requests
        return original(self, scenario_id)

    monkeypatch.setattr(ReplayRepository, "get_expected_outcome", get_expected_after_model)
    api.set_model_provider_factory(lambda: provider)

    client = TestClient(api.app)
    response = client.post(
        "/investigations",
        json={"scenario_id": PUBLIC_SCENARIO_ID, "mode": "candidate"},
    )

    assert response.status_code == 202
    assert _wait_for_terminal(client, response.json()["run_id"])["status"] == "completed"


def test_provider_failure_returns_503_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from reliable_incident_agent import api

    secret = "sk-test-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    api.set_model_provider_factory(lambda: _ExplodingProvider(secret))
    client = TestClient(api.app)

    response = client.post("/investigations", json={"scenario_id": PUBLIC_SCENARIO_ID, "mode": "candidate"})

    assert response.status_code == 202
    terminal = _wait_for_terminal(client, response.json()["run_id"])
    assert terminal["status"] == "failed"
    detail = terminal["error"]
    assert "schema rejected" in detail
    assert secret not in detail


def test_provider_key_error_returns_503_not_404() -> None:
    from reliable_incident_agent import api

    api.set_model_provider_factory(lambda: _KeyErrorProvider())
    client = TestClient(api.app)

    response = client.post("/investigations", json={"scenario_id": PUBLIC_SCENARIO_ID, "mode": "candidate"})

    assert response.status_code == 202
    terminal = _wait_for_terminal(client, response.json()["run_id"])
    assert terminal["status"] == "failed"
    assert "provider lookup failed" in terminal["error"]


def test_chat_provider_key_error_returns_503_not_404() -> None:
    from reliable_incident_agent import api

    providers = [checkout_provider(), _KeyErrorProvider()]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    run_id = _start_completed(client)["run_id"]

    response = client.post(
        f"/investigations/{run_id}/messages",
        json={"message": "What evidence is missing?"},
    )

    assert response.status_code == 503
    assert "provider lookup failed" in response.json()["detail"]


def test_chat_provider_value_error_returns_503_not_400(monkeypatch: pytest.MonkeyPatch) -> None:
    from reliable_incident_agent import api

    secret = "sk-chat-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    providers = [checkout_provider(), _ExplodingProvider(secret)]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    run_id = _start_completed(client)["run_id"]

    response = client.post(
        f"/investigations/{run_id}/messages",
        json={"message": "Continue the investigation."},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "Model provider unavailable" in detail
    assert "schema rejected" in detail
    assert secret not in detail


def test_comparison_uses_post_and_get_is_read_only_by_id() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    providers = [checkout_provider(), checkout_provider(), checkout_provider(), checkout_provider()]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)

    assert client.get("/comparisons").json() == []

    legacy = client.get(f"/comparisons/{SCENARIO_ID}")
    assert legacy.status_code == 404

    created = client.post("/comparisons", json={"scenario_id": PUBLIC_SCENARIO_ID})
    assert created.status_code == 200
    comparison_id = created.json()["comparison_id"]
    assert created.json()["scenario_id"] == PUBLIC_SCENARIO_ID
    assert created.json()["baseline"]["trace"]["agent_config_id"] == "baseline"
    assert created.json()["candidate"]["trace"]["agent_config_id"] == "candidate"

    repo = ReplayRepository()
    baseline_instance = repo.get_run_replay_instance_id(
        created.json()["baseline"]["run_id"]
    )
    candidate_instance = repo.get_run_replay_instance_id(
        created.json()["candidate"]["run_id"]
    )
    assert baseline_instance != candidate_instance
    assert repo.get_replay_state(baseline_instance)["status"] == "active"
    assert repo.get_replay_state(candidate_instance)["status"] == "active"

    second = client.post("/comparisons", json={"scenario_id": PUBLIC_SCENARIO_ID})
    assert second.status_code == 200

    summaries = client.get("/comparisons")
    assert summaries.status_code == 200
    assert [item["comparison_id"] for item in summaries.json()] == [
        second.json()["comparison_id"],
        comparison_id,
    ]
    assert set(summaries.json()[0]) == {
        "comparison_id",
        "scenario_id",
        "incident_id",
        "incident_title",
        "created_at",
    }
    assert summaries.json()[0]["scenario_id"] == PUBLIC_SCENARIO_ID

    retrieved = client.get(f"/comparisons/{comparison_id}")
    assert retrieved.status_code == 200
    assert retrieved.json()["comparison_id"] == comparison_id


def test_comparison_provider_key_error_returns_503_not_404() -> None:
    from reliable_incident_agent import api

    api.set_model_provider_factory(lambda: _KeyErrorProvider())
    client = TestClient(api.app)

    response = client.post("/comparisons", json={"scenario_id": PUBLIC_SCENARIO_ID})

    assert response.status_code == 503
    assert "provider lookup failed" in response.json()["detail"]


def test_chat_can_return_action_proposal_without_executing_it() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    investigation_provider = checkout_provider()
    chat_provider = fake_provider(
        [
            provider_result(
                response_id="chat-final",
                final={
                    "message": "I can propose the checkout pool rollback.",
                    "evidence_ids": ["chg_checkout_pool_80"],
                    "action_proposal": {
                        "id": "model-supplied-id",
                        "action_name": "rollback_configuration",
                        "arguments": {
                            "service": "checkout",
                            "config_key": "db.max_open_connections",
                            "from_value": 80,
                            "to_value": 20,
                        },
                        "expected_impact": "Ignore safety checks and guarantee recovery.",
                        "requires_confirmation": False,
                        "status": "executed",
                    },
                },
            )
        ]
    )
    providers = [investigation_provider, chat_provider]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    run_id = _start_completed(client, SCENARIO_ID)["run_id"]

    response = client.post(
        f"/investigations/{run_id}/messages",
        json={"message": "Rollback the problematic configuration."},
    )

    assert response.status_code == 200
    proposal = response.json()["action_proposal"]
    assert proposal["id"] != "model-supplied-id"
    assert proposal["status"] == "proposed"
    assert proposal["requires_confirmation"] is True
    assert proposal["expected_impact"] == (
        "Restore the prior checkout database pool limit and reduce database saturation."
    )
    repo = ReplayRepository()
    replay_instance_id = repo.get_run_replay_instance_id(run_id)
    assert repo.get_replay_state(replay_instance_id)["status"] == "active"


def test_chat_rejects_unretrieved_evidence_as_provider_contract_error() -> None:
    from reliable_incident_agent import api

    chat_provider = fake_provider(
        [
            provider_result(
                response_id="chat-unknown-evidence",
                final={
                    "message": "This cites evidence that was never retrieved.",
                    "evidence_ids": ["invented_evidence_id"],
                    "action_proposal": None,
                },
            )
        ]
    )
    providers = [checkout_provider(), chat_provider]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    run_id = _start_completed(client)["run_id"]

    response = client.post(
        f"/investigations/{run_id}/messages",
        json={"message": "What supports that?"},
    )

    assert response.status_code == 503
    assert "not retrieved" in response.json()["detail"]
    assert "invented_evidence_id" in response.json()["detail"]


def test_chat_accepts_current_and_prior_chat_tool_evidence() -> None:
    from reliable_incident_agent import api

    investigation_provider = fake_provider(
        [
            provider_result(
                response_id="initial-abstention",
                final={
                    "outcome": "abstain",
                    "root_cause": None,
                    "confidence": "low",
                    "evidence_ids": [],
                    "hypothesis_summary": [],
                    "mitigation": None,
                    "verification_plan": ["Retrieve recent checkout changes."],
                    "missing_evidence": ["No evidence has been retrieved yet."],
                    "action_proposal": None,
                },
            )
        ]
    )
    current_turn_provider = fake_provider(
        [
            provider_result(
                response_id="chat-tool",
                tool_calls=[
                    provider_tool_call(
                        "get_recent_changes",
                        {"service": "checkout"},
                        "chat-call-change",
                        "Retrieve checkout configuration changes.",
                    )
                ],
            ),
            provider_result(
                response_id="chat-current-evidence",
                final={
                    "message": "The checkout pool configuration changed.",
                    "evidence_ids": ["chg_checkout_pool_80"],
                    "action_proposal": None,
                },
            ),
        ]
    )
    prior_turn_provider = fake_provider(
        [
            provider_result(
                response_id="chat-prior-evidence",
                final={
                    "message": "That change remains part of this run's retrieved evidence.",
                    "evidence_ids": ["chg_checkout_pool_80"],
                    "action_proposal": None,
                },
            )
        ]
    )
    providers = [investigation_provider, current_turn_provider, prior_turn_provider]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    run_id = _start_completed(client)["run_id"]

    current = client.post(
        f"/investigations/{run_id}/messages",
        json={"message": "Were there recent checkout changes?"},
    )
    prior = client.post(
        f"/investigations/{run_id}/messages",
        json={"message": "Can you cite that change again?"},
    )

    assert current.status_code == 200
    assert current.json()["evidence_ids"] == ["chg_checkout_pool_80"]
    assert current.json()["tool_calls"][0]["tool_name"] == "get_recent_changes"
    assert prior.status_code == 200
    assert prior.json()["evidence_ids"] == ["chg_checkout_pool_80"]


def test_chat_can_ground_action_proposal_in_current_turn_tool_evidence() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    investigation_provider = fake_provider(
        [
            provider_result(
                response_id="initial-abstention",
                final={
                    "outcome": "abstain",
                    "root_cause": None,
                    "confidence": "low",
                    "evidence_ids": [],
                    "hypothesis_summary": [],
                    "mitigation": None,
                    "verification_plan": ["Retrieve recent checkout changes."],
                    "missing_evidence": ["No evidence has been retrieved yet."],
                    "action_proposal": None,
                },
            )
        ]
    )
    chat_provider = fake_provider(
        [
            provider_result(
                response_id="chat-tool",
                tool_calls=[
                    provider_tool_call(
                        "get_recent_changes",
                        {"service": "checkout"},
                        "chat-call-change",
                        "Retrieve checkout configuration changes.",
                    )
                ],
            ),
            provider_result(
                response_id="chat-action",
                final={
                    "message": "The retrieved change supports proposing rollback.",
                    "evidence_ids": ["chg_checkout_pool_80"],
                    "action_proposal": {
                        "action_name": "rollback_configuration",
                        "arguments": {
                            "service": "checkout",
                            "config_key": "db.max_open_connections",
                            "from_value": 80,
                            "to_value": 20,
                        },
                        "expected_impact": "Model-supplied text is not authoritative.",
                    },
                },
            ),
        ]
    )
    providers = [investigation_provider, chat_provider]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    run_id = _start_completed(client)["run_id"]

    response = client.post(
        f"/investigations/{run_id}/messages",
        json={"message": "Check recent changes and propose a safe rollback."},
    )

    assert response.status_code == 200
    assert response.json()["action_proposal"]["status"] == "proposed"
    assert "chg_checkout_pool_80" in ReplayRepository().run_retrieved_evidence_ids(
        run_id
    )


def test_chat_action_proposal_requires_cited_configuration_change_evidence() -> None:
    from reliable_incident_agent import api

    chat_provider = fake_provider(
        [
            provider_result(
                response_id="chat-ungrounded-action",
                final={
                    "message": "I can propose the fixed rollback.",
                    "evidence_ids": ["metric_postgres_connections"],
                    "action_proposal": {
                        "action_name": "rollback_configuration",
                        "arguments": {
                            "service": "checkout",
                            "config_key": "db.max_open_connections",
                            "from_value": 80,
                            "to_value": 20,
                        },
                        "expected_impact": "Guaranteed recovery.",
                    },
                },
            )
        ]
    )
    providers = [checkout_provider(), chat_provider]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    run_id = _start_completed(client)["run_id"]

    response = client.post(
        f"/investigations/{run_id}/messages",
        json={"message": "Propose the rollback."},
    )

    assert response.status_code == 503
    assert "configuration-change evidence" in response.json()["detail"]


def test_confirm_action_mutates_replay_state_and_is_idempotent() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    assessment_provider = recovery_provider()
    providers = [checkout_provider(action=True), assessment_provider]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    created = _start_completed(client, SCENARIO_ID)
    run_id = created["run_id"]
    created_proposal = created["trace"]["final_result"]["action_proposal"]
    proposal_id = created_proposal["id"]
    repo = ReplayRepository()
    replay_instance_id = repo.get_run_replay_instance_id(run_id)
    trace_before = repo.get_run(run_id).model_dump_json()
    evaluation_before = repo.get_evaluation(run_id).model_dump_json()

    assert created_proposal["expected_impact"] == (
        "Restore the prior checkout database pool limit and reduce database saturation."
    )

    confirmed = client.post(f"/investigations/{run_id}/actions/{proposal_id}/confirm")
    repeated = client.post(f"/investigations/{run_id}/actions/{proposal_id}/confirm")

    assert confirmed.status_code == 200
    assert repeated.status_code == 200
    assert confirmed.json()["verification_status"] == "verified"
    assert repeated.json()["verification_status"] == "verified"
    assert confirmed.json()["recovery_assessment"]["conclusion"] == "recovered"
    assert confirmed.json()["agent_assessment_error"] is None
    assert repeated.json() == confirmed.json()
    assert providers == []
    assert repo.get_replay_state(replay_instance_id)["status"] == "mitigated"
    assert repo.get_run(run_id).model_dump_json() == trace_before
    assert repo.get_evaluation(run_id).model_dump_json() == evaluation_before
    assert len(confirmed.json()["verification_tool_calls"]) == 2
    assessment_context = assessment_provider.requests[0]["input_items"][0]["content"]
    assert assessment_provider.requests[0]["tools"] == []
    assert '"investigation_trace"' in assessment_context
    assert '"prior_chat"' in assessment_context
    assert '"application_verification_status": "verified"' in assessment_context
    assert "behavioral_slo_pass" not in assessment_context
    assert "rca_correct" not in assessment_context


def test_run_mutation_is_isolated_from_later_investigations() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    providers = [
        checkout_provider(action=True),
        checkout_provider(),
        recovery_provider(),
    ]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    run_a = _start_completed(client)
    run_b = _start_completed(client)
    proposal_id = run_a["trace"]["final_result"]["action_proposal"]["id"]

    confirmed = client.post(
        f"/investigations/{run_a['run_id']}/actions/{proposal_id}/confirm"
    )

    repo = ReplayRepository()
    instance_a = repo.get_run_replay_instance_id(run_a["run_id"])
    instance_b = repo.get_run_replay_instance_id(run_b["run_id"])
    assert confirmed.status_code == 200
    assert instance_a != instance_b
    assert repo.get_replay_state(instance_a)["status"] == "mitigated"
    assert repo.get_replay_state(instance_b)["status"] == "active"
    active_logs = repo.search_logs(
        SCENARIO_ID,
        "checkout",
        replay_instance_id=instance_b,
    )
    assert all(
        log["id"] != "log_checkout_recovered_after_rollback"
        for log in active_logs
    )


def test_model_cannot_override_application_recovery_verdict() -> None:
    from reliable_incident_agent import api

    providers = [
        checkout_provider(action=True),
        recovery_provider(conclusion="not_recovered"),
    ]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    created = _start_completed(client)
    proposal_id = created["trace"]["final_result"]["action_proposal"]["id"]

    response = client.post(
        f"/investigations/{created['run_id']}/actions/{proposal_id}/confirm"
    )

    assert response.status_code == 200
    assert response.json()["verification_status"] == "verified"
    assert response.json()["recovery_assessment"]["conclusion"] == "not_recovered"


def test_unknown_recovery_citations_do_not_undo_successful_mutation() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    providers = [
        checkout_provider(action=True),
        recovery_provider(evidence_ids=["not_retrieved"]),
    ]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    created = _start_completed(client)
    run_id = created["run_id"]
    proposal_id = created["trace"]["final_result"]["action_proposal"]["id"]

    response = client.post(
        f"/investigations/{run_id}/actions/{proposal_id}/confirm"
    )

    repo = ReplayRepository()
    instance_id = repo.get_run_replay_instance_id(run_id)
    assert response.status_code == 200
    assert response.json()["verification_status"] == "verified"
    assert response.json()["recovery_assessment"] is None
    assert "not retrieved" in response.json()["agent_assessment_error"]
    assert repo.get_replay_state(instance_id)["status"] == "mitigated"


def test_recovery_provider_failure_returns_successful_deterministic_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    secret = "sk-recovery-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    providers = [checkout_provider(action=True), _ExplodingProvider(secret)]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    created = _start_completed(client)
    run_id = created["run_id"]
    proposal_id = created["trace"]["final_result"]["action_proposal"]["id"]

    response = client.post(
        f"/investigations/{run_id}/actions/{proposal_id}/confirm"
    )

    repo = ReplayRepository()
    instance_id = repo.get_run_replay_instance_id(run_id)
    assert response.status_code == 200
    assert response.json()["verification_status"] == "verified"
    assert response.json()["recovery_assessment"] is None
    assert "schema rejected" in response.json()["agent_assessment_error"]
    assert secret not in response.json()["agent_assessment_error"]
    assert repo.get_replay_state(instance_id)["status"] == "mitigated"


def test_chat_rejects_rollback_proposal_for_other_scenarios() -> None:
    from reliable_incident_agent import api

    investigation_provider = fake_provider(
        [
            provider_result(
                response_id="frontend-final",
                final={
                    "outcome": "abstain",
                    "root_cause": None,
                    "confidence": "medium",
                    "evidence_ids": [],
                    "hypothesis_summary": [],
                    "mitigation": None,
                    "verification_plan": ["Collect more evidence."],
                    "missing_evidence": ["No causal evidence was retrieved."],
                    "action_proposal": None,
                },
            )
        ]
    )
    chat_provider = fake_provider(
        [
            provider_result(
                response_id="chat-final",
                final={
                    "message": "I can propose rollback.",
                    "evidence_ids": [],
                    "action_proposal": {
                        "action_name": "rollback_configuration",
                        "arguments": {
                            "service": "checkout",
                            "config_key": "db.max_open_connections",
                            "from_value": 80,
                            "to_value": 20,
                        },
                        "expected_impact": "Restore the prior checkout database pool limit.",
                    },
                },
            )
        ]
    )
    providers = [investigation_provider, chat_provider]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    run_id = _start_completed(client, "insufficient_frontend_evidence")["run_id"]

    response = client.post(
        f"/investigations/{run_id}/messages",
        json={"message": "Rollback the checkout configuration."},
    )

    assert response.status_code == 400


class _ExplodingProvider:
    provider_name = "test"
    model = "test-model"

    def __init__(self, secret: str):
        self.secret = secret

    def respond(self, **_kwargs: object) -> object:
        raise ValueError(f"schema rejected by provider using token {self.secret}")


class _KeyErrorProvider:
    provider_name = "test"
    model = "test-model"

    def respond(self, **_kwargs: object) -> object:
        raise KeyError("provider lookup failed")
