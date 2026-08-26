from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from conftest import (
    SCENARIO_ID,
    checkout_provider,
    checkout_success_final,
    fake_provider,
    provider_result,
    provider_tool_call,
)


def test_provider_loop_executes_model_selected_tool_calls() -> None:
    from reliable_incident_agent.evaluator import evaluate_trace
    from reliable_incident_agent.investigator import run_investigation
    from reliable_incident_agent.replay import ReplayRepository

    provider = checkout_provider()
    repo = ReplayRepository()
    trace = run_investigation(SCENARIO_ID, "candidate", repo, provider)
    evaluation = evaluate_trace(trace, repo.get_expected_outcome(SCENARIO_ID))

    assert [call.tool_name for call in trace.tool_calls] == [
        "get_service_health",
        "get_dependencies",
        "get_metrics",
        "get_recent_changes",
        "search_logs",
        "search_logs",
    ]
    assert trace.agent_config_id == "candidate"
    assert trace.provider_metadata.provider == "fake"
    assert evaluation.rca_correct is True
    assert evaluation.behavioral_slo_pass is True


def test_tool_lookup_errors_do_not_leak_repository_or_scenario_details() -> None:
    from reliable_incident_agent.replay import ReplayRepository
    from reliable_incident_agent.tools import ObservabilityTools

    repo = ReplayRepository()
    replay_instance_id = repo.create_replay_instance(SCENARIO_ID)
    call = ObservabilityTools(
        SCENARIO_ID,
        repo,
        replay_instance_id,
    ).execute(
        "get_metrics",
        {"service": "not-a-service", "metric_name": None},
        "Test an unknown service.",
    )

    serialized = repr(call.result).lower()
    assert call.status == "error"
    assert call.result["error"] == "Requested observability data was not found."
    assert SCENARIO_ID not in serialized
    assert "select" not in serialized
    assert "params" not in serialized


def test_openai_provider_continues_statelessly_with_output_and_call_result() -> None:
    from reliable_incident_agent.investigator import run_investigation
    from reliable_incident_agent.providers import OpenAIResponsesProvider
    from reliable_incident_agent.replay import ReplayRepository

    client = _RecordingOpenAIClient(
        [
            SimpleNamespace(
                id="resp-tools",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="get_service_health",
                        arguments=json.dumps({"service": "checkout", "purpose": "Check health."}),
                        call_id="call-health",
                    )
                ],
                output_text="",
                usage=SimpleNamespace(input_tokens=10, output_tokens=20),
            ),
            SimpleNamespace(
                id="resp-final",
                output=[],
                output_text=json.dumps(checkout_success_final()),
                usage=SimpleNamespace(input_tokens=5, output_tokens=15),
            ),
        ]
    )
    provider = OpenAIResponsesProvider(model="test-openai-model", client=client)

    run_investigation(SCENARIO_ID, "candidate", ReplayRepository(), provider)

    assert len(client.requests) == 2
    assert "previous_response_id" not in client.requests[0]
    assert "previous_response_id" not in client.requests[1]
    assert client.requests[0]["store"] is False
    assert client.requests[0]["include"] == ["reasoning.encrypted_content"]
    assert client.requests[0]["input"][0]["role"] == "user"
    assert client.requests[1]["input"] == [
        client.requests[0]["input"][0],
        {
            "type": "function_call",
            "name": "get_service_health",
            "arguments": json.dumps(
                {"service": "checkout", "purpose": "Check health."}
            ),
            "call_id": "call-health",
        },
        {
            "type": "function_call_output",
            "call_id": "call-health",
            "output": client.requests[1]["input"][2]["output"],
        },
    ]
    assert "checkout" in client.requests[1]["input"][2]["output"]


def test_expected_outcome_is_not_sent_to_model_context() -> None:
    from reliable_incident_agent.investigator import run_investigation
    from reliable_incident_agent.replay import ReplayRepository

    provider = checkout_provider()
    run_investigation(SCENARIO_ID, "baseline", ReplayRepository(), provider)

    serialized_requests = repr(provider.requests).lower()
    assert "expected_outcomes" not in serialized_requests
    assert "checkout latency was caused by postgres connection exhaustion" not in serialized_requests
    assert "max_open_connections change from 20 to 80" not in serialized_requests


def test_baseline_and_candidate_differ_by_prompt_not_tool_availability() -> None:
    from reliable_incident_agent.investigator import AGENT_CONFIGS
    from reliable_incident_agent.tools import READ_TOOL_SCHEMAS

    assert AGENT_CONFIGS["baseline"].instructions != AGENT_CONFIGS["candidate"].instructions
    assert "pass" not in AGENT_CONFIGS["baseline"].instructions.lower()
    assert "fail" not in AGENT_CONFIGS["candidate"].instructions.lower()
    candidate_instructions = AGENT_CONFIGS["candidate"].instructions.lower()
    assert "eight-call read budget" in candidate_instructions
    assert "each serious causal branch" in candidate_instructions
    assert "avoid immediately repeating" in candidate_instructions
    assert {tool["name"] for tool in READ_TOOL_SCHEMAS} == {
        "get_service_health",
        "search_logs",
        "get_metrics",
        "get_dependencies",
        "get_recent_changes",
    }
    assert len(READ_TOOL_SCHEMAS) == 5
    for tool in READ_TOOL_SCHEMAS:
        parameters = tool["parameters"]
        assert tool.get("strict") is True
        assert parameters["additionalProperties"] is False
        assert set(parameters["properties"]) == set(parameters["required"])


def test_model_response_schemas_are_strict_and_closed() -> None:
    from reliable_incident_agent.investigator import (
        _chat_response_format,
        _final_response_format,
    )

    final_format = _final_response_format()
    final_schema = final_format["schema"]
    assert final_format["strict"] is True
    assert '"default"' not in json.dumps(final_schema)
    assert final_schema["properties"]["outcome"]["enum"] == [
        "root_cause",
        "abstain",
    ]
    assert set(final_schema["required"]) == set(final_schema["properties"])
    hypothesis_schema = final_schema["$defs"]["HypothesisFinding"]
    assert set(hypothesis_schema["required"]) == set(hypothesis_schema["properties"])

    for response_format in (final_format, _chat_response_format()):
        action_schema = response_format["schema"]["properties"]["action_proposal"][
            "anyOf"
        ][0]
        arguments_schema = action_schema["properties"]["arguments"]
        assert response_format["strict"] is True
        assert action_schema["additionalProperties"] is False
        assert arguments_schema["additionalProperties"] is False
        assert set(arguments_schema["required"]) == set(arguments_schema["properties"])


def test_model_cannot_return_application_error_outcome() -> None:
    from reliable_incident_agent.investigator import run_investigation
    from reliable_incident_agent.replay import ReplayRepository

    provider = fake_provider(
        [
            provider_result(
                response_id="model-error-outcome",
                final={
                    "outcome": "error",
                    "root_cause": None,
                    "confidence": "low",
                    "evidence_ids": [],
                    "hypothesis_summary": [],
                    "mitigation": None,
                    "verification_plan": [],
                    "missing_evidence": ["The model attempted an application-only outcome."],
                    "action_proposal": None,
                },
            )
        ]
    )

    trace = run_investigation(SCENARIO_ID, "candidate", ReplayRepository(), provider)

    assert trace.final_result.outcome == "error"
    assert trace.final_result.missing_evidence == [
        "Model outcome must be root_cause or abstain."
    ]


def test_budget_exhaustion_fails_explicitly_without_constant_rca() -> None:
    from reliable_incident_agent.investigator import run_investigation
    from reliable_incident_agent.replay import ReplayRepository

    responses = []
    for turn in range(10):
        responses.append(
            provider_result(
                response_id=f"resp-{turn}",
                tool_calls=[
                    provider_tool_call(
                        "get_service_health",
                        {"service": "checkout"},
                        f"call-{turn}",
                    )
                ],
            )
        )
    trace = run_investigation(SCENARIO_ID, "candidate", ReplayRepository(), fake_provider(responses))

    assert trace.final_result.outcome == "error"
    assert trace.final_root_cause == "Investigation failed before a defensible RCA was produced."


def test_final_result_rejects_unretrieved_evidence_ids() -> None:
    from reliable_incident_agent.investigator import run_investigation
    from reliable_incident_agent.replay import ReplayRepository

    provider = fake_provider(
        [
            provider_result(
                response_id="one-tool",
                tool_calls=[provider_tool_call("get_service_health", {"service": "checkout"}, "call-1")],
            ),
            provider_result(
                response_id="bad-final",
                final={
                    "outcome": "root_cause",
                    "root_cause": "Checkout failed because postgres connections were exhausted.",
                    "confidence": "high",
                    "evidence_ids": ["not_retrieved"],
                    "hypothesis_summary": [],
                    "mitigation": "Rollback checkout config.",
                    "verification_plan": [],
                    "missing_evidence": [],
                    "action_proposal": None,
                },
            ),
        ]
    )

    trace = run_investigation(SCENARIO_ID, "candidate", ReplayRepository(), provider)

    assert trace.final_result.outcome == "error"
    assert "not retrieved" in trace.final_result.missing_evidence[0]


def test_final_action_proposal_requires_cited_configuration_change_evidence() -> None:
    from reliable_incident_agent.investigator import run_investigation
    from reliable_incident_agent.replay import ReplayRepository

    provider = checkout_provider(action=True)
    final = provider.responses[-1].final
    assert final is not None
    final["evidence_ids"] = [
        evidence_id
        for evidence_id in final["evidence_ids"]
        if evidence_id != "chg_checkout_pool_80"
    ]

    trace = run_investigation(SCENARIO_ID, "candidate", ReplayRepository(), provider)

    assert trace.final_result.outcome == "error"
    assert "configuration-change evidence" in trace.final_result.missing_evidence[0]


def test_live_openai_provider_requires_explicit_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from reliable_incident_agent.providers import OpenAIResponsesProvider

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_MODEL"):
        OpenAIResponsesProvider()


def test_live_openai_provider_uses_bounded_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    from reliable_incident_agent.providers import (
        OPENAI_MAX_RETRIES,
        OPENAI_REQUEST_TIMEOUT_SECONDS,
        OpenAIResponsesProvider,
    )

    captured: dict[str, object] = {}

    def create_client(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=create_client))

    OpenAIResponsesProvider(model="test-openai-model")

    assert captured == {
        "timeout": OPENAI_REQUEST_TIMEOUT_SECONDS,
        "max_retries": OPENAI_MAX_RETRIES,
    }


def test_insufficient_evidence_abstention_is_valid_behavior() -> None:
    from reliable_incident_agent.evaluator import evaluate_trace
    from reliable_incident_agent.investigator import run_investigation
    from reliable_incident_agent.replay import ReplayRepository

    provider = fake_provider(
        [
            provider_result(
                response_id="frontend-tools",
                tool_calls=[
                    provider_tool_call("get_service_health", {"service": "frontend"}, "call-1"),
                    provider_tool_call("search_logs", {"service": "frontend", "query": "render failed"}, "call-2"),
                    provider_tool_call("get_dependencies", {"service": "frontend"}, "call-3"),
                    provider_tool_call("get_recent_changes", {"service": "frontend"}, "call-4"),
                ],
            ),
            provider_result(
                response_id="frontend-final",
                final={
                    "outcome": "abstain",
                    "root_cause": None,
                    "confidence": "medium",
                    "evidence_ids": [
                        "log3_frontend_product_error",
                        "dep3_frontend_checkout",
                        "neg_frontend_get_recent_changes_changes_none",
                    ],
                    "hypothesis_summary": [
                        {
                            "hypothesis": "Frontend render path failed after cache miss.",
                            "status": "unresolved",
                            "evidence_ids": ["log3_frontend_product_error"],
                        }
                    ],
                    "mitigation": None,
                    "verification_plan": ["Collect cache and render-service evidence."],
                    "missing_evidence": [
                        "No frontend change evidence was retrieved to establish deployment causality."
                    ],
                    "action_proposal": None,
                },
            ),
        ]
    )
    repo = ReplayRepository()
    trace = run_investigation("insufficient_frontend_evidence", "candidate", repo, provider)
    evaluation = evaluate_trace(trace, repo.get_expected_outcome("insufficient_frontend_evidence"))

    assert trace.final_result.outcome == "abstain"
    assert evaluation.rca_correct is True
    assert evaluation.behavioral_slo_pass is True


class _RecordingOpenAIClient:
    def __init__(self, responses: list[SimpleNamespace]):
        self.requests: list[dict[str, object]] = []
        self.responses = _RecordingResponses(self.requests, responses)


class _RecordingResponses:
    def __init__(self, requests: list[dict[str, object]], responses: list[SimpleNamespace]):
        self._requests = requests
        self._responses = list(responses)

    def create(self, **kwargs: object) -> SimpleNamespace:
        self._requests.append(kwargs)
        if not self._responses:
            raise AssertionError("No queued OpenAI test response.")
        return self._responses.pop(0)
