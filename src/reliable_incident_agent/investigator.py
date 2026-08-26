"""Provider-injected LLM investigator runtime over deterministic replay tools."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from pydantic import ValidationError

from .models import (
    ActionConfirmationResponse,
    ActionProposal,
    AgentMode,
    ChatMessageResponse,
    InvestigationFinalResult,
    InvestigationTrace,
    ProviderMetadata,
    RecoveryAssessment,
    ToolCall,
)
from .providers import ModelProvider, OpenAIResponsesProvider
from .replay import (
    CHECKOUT_ROLLBACK_ARGUMENTS,
    CHECKOUT_ROLLBACK_EVIDENCE_ID,
    CHECKOUT_ROLLBACK_EXPECTED_IMPACT,
    CHECKOUT_ROLLBACK_SCENARIO_ID,
    ReplayRepository,
    internal_scenario_id,
)
from .tools import READ_TOOL_SCHEMAS, TOOL_SCHEMA_VERSION, ObservabilityTools

PROMPT_VERSION = "incident-investigator-v2"
MAX_READ_TOOL_CALLS = 8
MAX_MODEL_TURNS = 10
ProgressCallback = Callable[[str, str, dict[str, Any]], None]


class ProviderExecutionError(RuntimeError):
    """Raised when the model provider fails before returning a usable response."""


@dataclass(frozen=True)
class AgentConfig:
    id: AgentMode
    instructions: str
    temperature: float = 0

    @property
    def prompt_hash(self) -> str:
        return hashlib.sha256(self.instructions.encode("utf-8")).hexdigest()[:12]


AGENT_CONFIGS: dict[AgentMode, AgentConfig] = {
    "baseline": AgentConfig(
        id="baseline",
        instructions=(
            "You are an incident investigator. Investigate the incident with the "
            "available observability tools. Determine the most defensible root "
            "cause and recommend mitigation. If the evidence is insufficient, "
            "say so. Cite evidence IDs returned by tools. Do not invent evidence."
        ),
    ),
    "candidate": AgentConfig(
        id="candidate",
        instructions=(
            "You are an incident investigator. Maintain two to four plausible "
            "hypotheses, choose evidence that discriminates between them, update "
            "hypothesis status after observations, ground causal claims in "
            "retrieved evidence, and do not conclude until evidence is sufficient. "
            "Plan within an eight-call read budget: map dependencies early, test "
            "each serious causal branch with at least one discriminating observation, "
            "then deepen the leading hypothesis. Treat service health as a broad "
            "summary and avoid immediately repeating it with an unfiltered metric "
            "query for the same service; each additional call should seek new signal. "
            "If evidence is insufficient, abstain and identify missing evidence. "
            "Recommend mitigation and a verification plan. Cite evidence IDs."
        ),
    ),
}


def default_provider() -> ModelProvider:
    return OpenAIResponsesProvider()


def run_investigation(
    scenario_id: str,
    mode: AgentMode = "candidate",
    repository: Optional[ReplayRepository] = None,
    provider: Optional[ModelProvider] = None,
    replay_instance_id: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
    deadline_monotonic: Optional[float] = None,
) -> InvestigationTrace:
    scenario_id = internal_scenario_id(scenario_id)
    repo = repository or ReplayRepository()
    replay_instance_id = replay_instance_id or repo.create_replay_instance(scenario_id)
    model_provider = provider or default_provider()
    config = AGENT_CONFIGS[mode]
    incident_context = repo.get_agent_context(scenario_id)
    tools = ObservabilityTools(scenario_id, repo, replay_instance_id)
    input_items = [_user_item(_incident_prompt(incident_context))]
    response_ids: list[str] = []
    input_tokens = 0
    output_tokens = 0
    latency_ms = 0
    final_result: Optional[InvestigationFinalResult] = None

    for _turn in range(MAX_MODEL_TURNS):
        if _deadline_reached(deadline_monotonic):
            final_result = _error_result("Investigation execution deadline exceeded.")
            break
        response = _provider_respond(
            model_provider,
            instructions=_instructions(config),
            input_items=input_items,
            tools=READ_TOOL_SCHEMAS,
            response_format=_final_response_format(),
        )
        response_ids.append(response.response_id)
        input_tokens += response.input_tokens or 0
        output_tokens += response.output_tokens or 0
        latency_ms += response.latency_ms

        if _deadline_reached(deadline_monotonic):
            final_result = _error_result("Investigation execution deadline exceeded.")
            break

        if response.tool_calls:
            if len([call for call in tools.calls if call.status == "ok"]) >= MAX_READ_TOOL_CALLS:
                final_result = _error_result("Tool-call budget exhausted before final result.")
                break
            for requested in response.tool_calls:
                if len([call for call in tools.calls if call.status == "ok"]) >= MAX_READ_TOOL_CALLS:
                    input_items.append(_tool_error_item(requested.call_id, "Tool-call budget exhausted."))
                    continue
                sequence = len(tools.calls) + 1
                purpose = (
                    requested.purpose
                    or str(requested.arguments.get("purpose") or "")
                    or f"Use {requested.name} to gather incident evidence."
                )
                _emit_progress(
                    progress_callback,
                    "tool.started",
                    purpose or f"Running {requested.name}",
                    {
                        "sequence": sequence,
                        "tool_name": requested.name,
                        "purpose": purpose,
                    },
                )
                tool_call = tools.execute(
                    requested.name,
                    requested.arguments,
                    purpose=purpose,
                )
                _emit_progress(
                    progress_callback,
                    "tool.completed",
                    purpose or f"Completed {requested.name}",
                    {"tool_call": tool_call.model_dump(mode="json")},
                )
                input_items.append(_tool_output_item(requested.call_id, tool_call))
            continue

        if response.final is None:
            final_result = _error_result("Model returned neither tool calls nor structured final output.")
            break

        final_result = _validate_final_result(response.final, tools.calls, scenario_id)
        if final_result.hypothesis_summary:
            _emit_progress(
                progress_callback,
                "hypotheses.updated",
                "Hypotheses updated from retrieved evidence",
                {
                    "hypotheses": [
                        finding.model_dump(mode="json")
                        for finding in final_result.hypothesis_summary
                    ]
                },
            )
        break

    if final_result is None:
        final_result = _error_result("Model turn budget exhausted before final result.")

    final_root_cause = final_result.root_cause or (
        "Insufficient evidence to determine a single root cause."
        if final_result.outcome == "abstain"
        else "Investigation failed before a defensible RCA was produced."
    )
    provider_metadata = ProviderMetadata(
        provider=model_provider.provider_name,
        model=model_provider.model,
        response_ids=response_ids,
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
        latency_ms=latency_ms or None,
    )
    return InvestigationTrace(
        incident_id=str(incident_context["id"]),
        incident_description=_incident_description(incident_context),
        agent_config_id=mode,
        prompt_version=f"{PROMPT_VERSION}:{config.prompt_hash}",
        tool_schema_version=TOOL_SCHEMA_VERSION,
        model=model_provider.model,
        hypotheses=[finding.hypothesis for finding in final_result.hypothesis_summary],
        tool_calls=tools.calls,
        final_result=final_result,
        provider_metadata=provider_metadata,
        final_root_cause=final_root_cause,
    )


def _deadline_reached(deadline_monotonic: Optional[float]) -> bool:
    return deadline_monotonic is not None and time.monotonic() >= deadline_monotonic


def _emit_progress(
    callback: Optional[ProgressCallback],
    event_type: str,
    summary: str,
    payload: dict[str, Any],
) -> None:
    if callback is not None:
        callback(event_type, summary, payload)


def continue_investigation_chat(
    run_id: str,
    message: str,
    repository: Optional[ReplayRepository] = None,
    provider: Optional[ModelProvider] = None,
) -> ChatMessageResponse:
    repo = repository or ReplayRepository()
    trace = repo.get_run(run_id)
    run_scope = repo.get_run_scope(run_id)
    scenario_id = run_scope["scenario_id"]
    replay_instance_id = run_scope["replay_instance_id"]
    model_provider = provider or default_provider()
    tools = ObservabilityTools(scenario_id, repo, replay_instance_id)
    prior_chat = repo.get_chat_messages(run_id)
    repo.persist_chat_user_message(run_id, message)
    input_items = [
        _user_item(
            "Continue this incident investigation using only retrieved evidence "
            "or additional read tools. Never execute rollback from chat alone.\n\n"
            f"Existing trace:\n{trace.model_dump_json()}\n\nUser: {message}"
            f"\n\nPrior chat:\n{json.dumps(prior_chat, default=str)}"
            f"\n\nAction state:\n{json.dumps(repo.get_action_state(run_id), default=str)}"
        )
    ]
    final: Optional[dict[str, Any]] = None
    remaining_tool_budget = max(0, MAX_READ_TOOL_CALLS - repo.count_context_tool_calls(run_id))
    for _turn in range(4):
        response = _provider_respond(
            model_provider,
            instructions=_chat_instructions(),
            input_items=input_items,
            tools=READ_TOOL_SCHEMAS,
            response_format=_chat_response_format(),
        )
        if response.tool_calls:
            for requested in response.tool_calls:
                if remaining_tool_budget <= 0:
                    input_items.append(_tool_error_item(requested.call_id, "Run tool-call budget exhausted."))
                    continue
                tool_call = tools.execute(
                    requested.name,
                    requested.arguments,
                    purpose=requested.purpose,
                )
                if tool_call.status == "ok":
                    remaining_tool_budget -= 1
                input_items.append(_tool_output_item(requested.call_id, tool_call))
            continue
        final = response.final
        break
    if final is None:
        raise RuntimeError("Chat model did not return a structured response.")

    proposal = _proposal_from_payload(final.get("action_proposal"))
    evidence_ids = [str(item) for item in final.get("evidence_ids", [])]
    retrieved_evidence_ids = _chat_retrieved_evidence_ids(trace, prior_chat, tools.calls)
    unknown_evidence_ids = set(evidence_ids) - retrieved_evidence_ids
    if unknown_evidence_ids:
        raise ProviderExecutionError(
            "Chat output cited evidence IDs that were not retrieved: "
            f"{sorted(unknown_evidence_ids)}"
        )
    if proposal:
        _validate_rollback_proposal(proposal)
        if scenario_id != CHECKOUT_ROLLBACK_SCENARIO_ID:
            raise ValueError("Rollback proposals are only allowed for checkout_db_pool_exhaustion.")
        if CHECKOUT_ROLLBACK_EVIDENCE_ID not in evidence_ids:
            raise ProviderExecutionError(
                "Rollback proposal requires cited checkout configuration-change evidence."
            )
    response_model = ChatMessageResponse(
        run_id=run_id,
        message=str(final.get("message") or ""),
        evidence_ids=evidence_ids,
        tool_calls=tools.calls,
        action_proposal=proposal,
    )
    if proposal:
        repo.persist_action_proposal(
            run_id,
            proposal,
            additional_evidence_ids=retrieved_evidence_ids,
        )
    repo.persist_chat_response(response_model)
    return response_model


def confirm_rollback(
    run_id: str,
    proposal_id: str,
    repository: Optional[ReplayRepository] = None,
    provider_factory: Optional[Callable[[], ModelProvider]] = None,
) -> ActionConfirmationResponse:
    repo = repository or ReplayRepository()
    stored_run_id, proposal, _verification_status = repo.get_action_proposal(proposal_id)
    if stored_run_id != run_id:
        raise ValueError("Action proposal does not belong to this run.")
    run_scope = repo.get_run_scope(run_id)
    scenario_id = run_scope["scenario_id"]
    replay_instance_id = run_scope["replay_instance_id"]
    if scenario_id != CHECKOUT_ROLLBACK_SCENARIO_ID:
        raise ValueError("Only checkout_db_pool_exhaustion supports replay mutation.")
    if proposal.status == "executed":
        return repo.get_action_result(proposal_id)
    if proposal.status != "proposed":
        raise ValueError("Action proposal is not pending confirmation.")
    _validate_rollback_proposal(proposal)
    if CHECKOUT_ROLLBACK_EVIDENCE_ID not in repo.run_retrieved_evidence_ids(run_id):
        raise ValueError("Rollback confirmation requires retrieved configuration-change evidence.")
    result = repo.rollback_checkout_pool(replay_instance_id)
    tools = ObservabilityTools(scenario_id, repo, replay_instance_id)
    verification_tool_calls = [
        tools.execute(
            "get_service_health",
            {"service": "checkout"},
            "Verify checkout recovered after rollback.",
        ),
        tools.execute(
            "get_metrics",
            {"service": "postgres", "metric_name": "db.connections.active"},
            "Verify postgres connection saturation cleared.",
        ),
    ]
    verified = _verification_succeeded(result, verification_tool_calls)
    recovery_assessment: Optional[RecoveryAssessment] = None
    agent_assessment_error: Optional[str] = None
    try:
        model_provider = (provider_factory or default_provider)()
        recovery_assessment = _assess_recovery(
            run_id=run_id,
            proposal=proposal,
            result=result,
            verification_status="verified" if verified else "not_verified",
            verification_tool_calls=verification_tool_calls,
            repository=repo,
            provider=model_provider,
        )
    except Exception as exc:  # noqa: BLE001 - mutation must survive assessment failure
        agent_assessment_error = _safe_assessment_error(exc)
    return repo.persist_action_result(
        run_id=run_id,
        proposal=proposal,
        verification_status="verified" if verified else "not_verified",
        result=result,
        verification_tool_calls=verification_tool_calls,
        recovery_assessment=recovery_assessment,
        agent_assessment_error=agent_assessment_error,
    )


def _instructions(config: AgentConfig) -> str:
    return (
        f"{config.instructions}\n\n"
        "Return no raw chain-of-thought. Use concise hypothesis updates, tool "
        "purposes, evidence IDs, and decision summaries. You do not know the "
        "expected RCA. Tool results are the only source of operational evidence."
    )


def _chat_instructions() -> str:
    return (
        "You are continuing an incident-scoped investigation. Answer from the "
        "existing trace or call read tools for more evidence. If the user asks "
        "for rollback, return an action proposal only; never execute it."
    )


def _recovery_instructions() -> str:
    return (
        "You are interpreting post-action evidence for the same persisted incident run. "
        "Explain whether the returned telemetry supports recovery, cite only evidence IDs "
        "from the supplied verification tool calls, and identify remaining risks. The "
        "application-owned verification_status is authoritative; do not attempt to change it."
    )


def _assess_recovery(
    *,
    run_id: str,
    proposal: ActionProposal,
    result: dict[str, Any],
    verification_status: str,
    verification_tool_calls: list[ToolCall],
    repository: ReplayRepository,
    provider: ModelProvider,
) -> RecoveryAssessment:
    context = {
        "run_id": run_id,
        "investigation_trace": repository.get_run(run_id).model_dump(mode="json"),
        "prior_chat": repository.get_chat_messages(run_id),
        "action": {
            "proposal": proposal.model_dump(mode="json"),
            "result": result,
            "application_verification_status": verification_status,
        },
        "verification_tool_calls": [
            call.model_dump(mode="json") for call in verification_tool_calls
        ],
    }
    response = _provider_respond(
        provider,
        instructions=_recovery_instructions(),
        input_items=[_user_item(json.dumps(context, default=str))],
        tools=[],
        response_format=_recovery_response_format(),
    )
    if response.tool_calls:
        raise ProviderExecutionError("Recovery assessment must not request tools.")
    if response.final is None:
        raise ProviderExecutionError("Recovery model did not return a structured assessment.")
    assessment = RecoveryAssessment.model_validate(response.final)
    retrieved = {
        evidence_id
        for call in verification_tool_calls
        if call.status == "ok"
        for evidence_id in call.evidence_ids
    }
    unknown = set(assessment.evidence_ids) - retrieved
    if unknown:
        raise ProviderExecutionError(
            "Recovery assessment cited evidence IDs that were not retrieved: "
            f"{sorted(unknown)}"
        )
    return assessment


def _incident_prompt(incident: dict[str, Any]) -> str:
    return (
        "Investigate this incident.\n"
        f"Incident ID: {incident['id']}\n"
        f"Title: {incident['title']}\n"
        f"Severity: {incident['severity']}\n"
        f"Started at: {incident['started_at']}\n"
        f"Affected service: {incident['affected_service']}\n"
        f"Customer impact: {incident['customer_impact']}\n"
        f"Symptoms: {json.dumps(incident['symptoms'])}"
    )


def _incident_description(incident: dict[str, Any]) -> str:
    symptoms = "; ".join(str(item) for item in incident.get("symptoms", []))
    return (
        f"{incident['title']}. Impact: {incident['customer_impact']} "
        f"Symptoms: {symptoms}"
    )


def _user_item(content: str) -> dict[str, Any]:
    return {"role": "user", "content": content}


def _tool_output_item(call_id: str, tool_call: ToolCall) -> dict[str, Any]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": tool_call.model_dump_json(),
    }


def _tool_error_item(call_id: str, message: str) -> dict[str, Any]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps({"status": "error", "error": message}),
    }


def _final_response_format() -> dict[str, Any]:
    schema = InvestigationFinalResult.model_json_schema()
    definitions = schema.get("$defs", {})
    definitions.pop("ActionProposal", None)
    hypothesis_schema = definitions.get("HypothesisFinding")
    if isinstance(hypothesis_schema, dict):
        hypothesis_schema["required"] = list(hypothesis_schema.get("properties", {}))
    schema["properties"]["action_proposal"] = {
        "anyOf": [_action_proposal_response_schema(), {"type": "null"}]
    }
    schema["properties"]["outcome"] = {
        "type": "string",
        "enum": ["root_cause", "abstain"],
    }
    schema["required"] = list(schema["properties"])
    _remove_schema_keyword(schema, "default")
    return {
        "type": "json_schema",
        "name": "investigation_final",
        "strict": True,
        "schema": schema,
    }


def _remove_schema_keyword(value: Any, keyword: str) -> None:
    if isinstance(value, dict):
        value.pop(keyword, None)
        for child in value.values():
            _remove_schema_keyword(child, keyword)
    elif isinstance(value, list):
        for child in value:
            _remove_schema_keyword(child, keyword)


def _chat_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "incident_chat_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "action_proposal": {
                    "anyOf": [_action_proposal_response_schema(), {"type": "null"}]
                },
            },
            "required": ["message", "evidence_ids", "action_proposal"],
            "additionalProperties": False,
        },
    }


def _action_proposal_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action_name": {
                "type": "string",
                "const": "rollback_configuration",
            },
            "arguments": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "const": "checkout"},
                    "config_key": {
                        "type": "string",
                        "const": "db.max_open_connections",
                    },
                    "from_value": {"type": "integer", "const": 80},
                    "to_value": {"type": "integer", "const": 20},
                },
                "required": [
                    "service",
                    "config_key",
                    "from_value",
                    "to_value",
                ],
                "additionalProperties": False,
            },
            "expected_impact": {"type": "string"},
        },
        "required": ["action_name", "arguments", "expected_impact"],
        "additionalProperties": False,
    }


def _recovery_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "recovery_assessment",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "conclusion": {
                    "type": "string",
                    "enum": ["recovered", "not_recovered", "uncertain"],
                },
                "summary": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "remaining_risks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["conclusion", "summary", "evidence_ids", "remaining_risks"],
            "additionalProperties": False,
        },
    }


def _provider_respond(
    model_provider: ModelProvider,
    *,
    instructions: str,
    input_items: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    response_format: dict[str, Any],
) -> Any:
    try:
        return model_provider.respond(
            instructions=instructions,
            input_items=input_items,
            tools=tools,
            response_format=response_format,
        )
    except Exception as exc:
        raise ProviderExecutionError(str(exc) or exc.__class__.__name__) from exc


def _safe_assessment_error(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError) or isinstance(exc.__cause__, json.JSONDecodeError):
        detail = "provider returned malformed JSON"
    elif isinstance(exc, ValidationError):
        detail = "provider returned an invalid recovery assessment"
    else:
        detail = str(exc) or exc.__class__.__name__
    for name, value in os.environ.items():
        if ("KEY" in name or "TOKEN" in name or "SECRET" in name) and value:
            detail = detail.replace(value, "[redacted]")
    if len(detail) > 200:
        detail = detail[:197] + "..."
    return f"Recovery assessment unavailable: {detail}"


def _validate_final_result(
    payload: dict[str, Any],
    tool_calls: list[ToolCall],
    scenario_id: str,
) -> InvestigationFinalResult:
    payload = dict(payload)
    if isinstance(payload.get("action_proposal"), dict):
        payload["action_proposal"] = _normalize_action_payload(payload["action_proposal"])
    try:
        result = InvestigationFinalResult.model_validate(payload)
    except ValidationError as exc:
        return _error_result(f"Malformed final output: {exc.errors()}")
    contract_error = _final_contract_error(result, tool_calls, scenario_id)
    return _error_result(contract_error) if contract_error else result


def _proposal_from_payload(payload: Any) -> Optional[ActionProposal]:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise TypeError("action_proposal must be an object or null.")
    return ActionProposal.model_validate(_normalize_action_payload(payload))


def _normalize_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["id"] = f"act_{uuid.uuid4().hex}"
    normalized.setdefault("action_name", "rollback_configuration")
    normalized["expected_impact"] = CHECKOUT_ROLLBACK_EXPECTED_IMPACT
    normalized["requires_confirmation"] = True
    normalized["status"] = "proposed"
    return normalized


def _validate_rollback_proposal(proposal: ActionProposal) -> None:
    if proposal.action_name != "rollback_configuration":
        raise ValueError("Only rollback_configuration is supported.")
    if proposal.arguments != CHECKOUT_ROLLBACK_ARGUMENTS:
        raise ValueError(f"Rollback proposal must exactly match {CHECKOUT_ROLLBACK_ARGUMENTS}.")
    if proposal.expected_impact != CHECKOUT_ROLLBACK_EXPECTED_IMPACT:
        raise ValueError("Rollback proposal expected impact is not canonical.")


def _final_contract_error(
    result: InvestigationFinalResult,
    tool_calls: list[ToolCall],
    scenario_id: str,
) -> Optional[str]:
    retrieved = {
        evidence_id
        for call in tool_calls
        if call.status == "ok"
        for evidence_id in call.evidence_ids
    }
    cited = set(result.evidence_ids)
    cited.update(evidence_id for finding in result.hypothesis_summary for evidence_id in finding.evidence_ids)
    if cited and not cited <= retrieved:
        return "Final output cited evidence IDs that were not retrieved by tools."
    if result.outcome == "root_cause":
        if not result.root_cause:
            return "Root-cause outcome requires a non-empty root_cause."
        if not result.evidence_ids:
            return "Root-cause outcome requires cited retrieved evidence IDs."
    elif result.outcome == "abstain":
        if result.root_cause:
            return "Abstain outcome must not assert a root_cause."
        if not result.missing_evidence:
            return "Abstain outcome requires missing_evidence."
        if result.evidence_ids and not set(result.evidence_ids) <= retrieved:
            return "Abstain output cited evidence IDs that were not retrieved by tools."
    else:
        return "Model outcome must be root_cause or abstain."
    if result.action_proposal:
        try:
            _validate_rollback_proposal(result.action_proposal)
        except ValueError as exc:
            return str(exc)
        if scenario_id != CHECKOUT_ROLLBACK_SCENARIO_ID:
            return "Action proposals are only allowed for checkout_db_pool_exhaustion."
        if CHECKOUT_ROLLBACK_EVIDENCE_ID not in result.evidence_ids:
            return "Rollback proposal requires cited checkout configuration-change evidence."
    return None


def _chat_retrieved_evidence_ids(
    trace: InvestigationTrace,
    prior_chat: list[dict[str, Any]],
    current_tool_calls: list[ToolCall],
) -> set[str]:
    retrieved = {
        evidence_id
        for call in trace.tool_calls
        if call.status == "ok"
        for evidence_id in call.evidence_ids
    }
    for message in prior_chat:
        for payload in message.get("tool_calls", []):
            try:
                call = ToolCall.model_validate(payload)
            except ValidationError:
                continue
            if call.status == "ok":
                retrieved.update(call.evidence_ids)
    for call in current_tool_calls:
        if call.status == "ok":
            retrieved.update(call.evidence_ids)
    return retrieved


def _verification_succeeded(result: dict[str, Any], tool_calls: list[ToolCall]) -> bool:
    if result.get("status") != "mitigated" or result.get("checkout_db_pool_connections") != 20:
        return False
    if any(call.status != "ok" for call in tool_calls):
        return False
    checkout_health = next((call.result for call in tool_calls if call.tool_name == "get_service_health"), {})
    postgres_metrics = next((call.result for call in tool_calls if call.tool_name == "get_metrics"), {})
    return (
        checkout_health.get("service") == "checkout"
        and _metric_latest_below_threshold(checkout_health, "http.server.duration.p95_ms")
        and _metric_latest_below_threshold(checkout_health, "http.server.errors.percent")
        and _metric_latest_below_threshold(postgres_metrics, "db.connections.active")
    )


def _metric_latest_below_threshold(container: dict[str, Any], metric_name: str) -> bool:
    metrics = container.get("metrics", [])
    for metric in metrics:
        if metric.get("name") != metric_name:
            continue
        points = metric.get("points") or []
        threshold = metric.get("threshold")
        if not points or threshold is None:
            return False
        return float(points[-1]["value"]) < float(threshold)
    return False


def _error_result(message: str) -> InvestigationFinalResult:
    return InvestigationFinalResult(
        outcome="error",
        root_cause=None,
        confidence="low",
        missing_evidence=[message],
    )
