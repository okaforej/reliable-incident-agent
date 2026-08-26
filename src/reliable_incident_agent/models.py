"""Pydantic contracts shared by runtime, API, UI, and evaluator."""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AgentMode = Literal["baseline", "candidate"]
Outcome = Literal["root_cause", "abstain", "error"]
Confidence = Literal["low", "medium", "high"]
ToolStatus = Literal["ok", "error"]
ActionStatus = Literal["proposed", "executed", "rejected"]
ActionVerificationStatus = Literal["pending", "verified", "not_verified"]
RecoveryConclusion = Literal["recovered", "not_recovered", "uncertain"]
InvestigationRunState = Literal["queued", "running", "completed", "failed"]
InvestigationEventType = Literal[
    "investigation.started",
    "hypotheses.updated",
    "tool.started",
    "tool.completed",
    "investigation.completed",
    "investigation.failed",
]


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    tool_name: str
    purpose: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    status: ToolStatus = "ok"
    duration_ms: int = Field(default=0, ge=0)


class HypothesisFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis: str
    status: Literal["supported", "weakened", "unresolved"]
    evidence_ids: list[str] = Field(default_factory=list)


class ActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action_name: Literal["rollback_configuration"]
    arguments: dict[str, Any]
    expected_impact: str
    requires_confirmation: bool = True
    status: ActionStatus = "proposed"


class InvestigationFinalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Outcome
    root_cause: Optional[str] = None
    confidence: Confidence = "low"
    evidence_ids: list[str] = Field(default_factory=list)
    hypothesis_summary: list[HypothesisFinding] = Field(default_factory=list)
    mitigation: Optional[str] = None
    verification_plan: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    action_proposal: Optional[ActionProposal] = None


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    response_ids: list[str] = Field(default_factory=list)
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None


class InvestigationTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    incident_description: str
    agent_config_id: AgentMode
    prompt_version: str
    tool_schema_version: str
    model: str
    hypotheses: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    final_result: InvestigationFinalResult
    provider_metadata: ProviderMetadata
    final_root_cause: str


class ExpectedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_cause: str


class BehavioralEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rca_correct: bool
    grounded: bool
    investigation_sufficient: bool
    tool_efficient: bool
    behavioral_slo_pass: bool
    reasons: list[str] = Field(default_factory=list)


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    mode: AgentMode = "candidate"
    live: bool = True


class InvestigationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    trace: InvestigationTrace
    evaluation: Optional[BehavioralEvaluation] = None


class InvestigationAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    scenario_id: str
    status: Literal["queued", "running"]


class InvestigationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    scenario_id: str
    incident_id: str
    incident_title: str
    status: InvestigationRunState
    outcome: Optional[Outcome] = None
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def validate_completed_outcome(self) -> InvestigationSummary:
        if self.status == "completed" and self.outcome is None:
            raise ValueError("completed investigation summary requires outcome")
        if self.status != "completed" and self.outcome is not None:
            raise ValueError("only completed investigation summary may include outcome")
        return self


class InvestigationStartedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    incident_id: str
    agent_config_id: AgentMode


class HypothesesUpdatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypotheses: list[HypothesisFinding]


class ToolStartedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    tool_name: str
    purpose: str


class ToolCompletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call: ToolCall


class InvestigationCompletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_count: int = Field(ge=0)


class InvestigationFailedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str


InvestigationEventPayload = Union[  # noqa: UP007 - runtime supports Python 3.9
    InvestigationStartedPayload,
    HypothesesUpdatedPayload,
    ToolStartedPayload,
    ToolCompletedPayload,
    InvestigationCompletedPayload,
    InvestigationFailedPayload,
]


class InvestigationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    run_id: str
    type: InvestigationEventType
    created_at: str
    summary: str
    payload: InvestigationEventPayload

    @model_validator(mode="after")
    def validate_typed_payload(self) -> InvestigationEvent:
        expected_payload = {
            "investigation.started": InvestigationStartedPayload,
            "hypotheses.updated": HypothesesUpdatedPayload,
            "tool.started": ToolStartedPayload,
            "tool.completed": ToolCompletedPayload,
            "investigation.completed": InvestigationCompletedPayload,
            "investigation.failed": InvestigationFailedPayload,
        }[self.type]
        if not isinstance(self.payload, expected_payload):
            raise TypeError(f"{self.type} has the wrong payload type")
        return self


class ScenarioSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    incident_id: str
    severity: str
    affected_service: str
    started_at: str
    customer_impact: str
    target_sli: str
    status: Literal["active"] = "active"
    symptoms: list[str] = Field(default_factory=list)


class ScenarioDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    incident: dict[str, Any]
    services: list[dict[str, Any]]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    openai_api_key_configured: bool
    openai_model: Optional[str] = None


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("message must contain non-whitespace text")
        return message


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    message: str
    evidence_ids: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    action_proposal: Optional[ActionProposal] = None


class RecoveryAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conclusion: RecoveryConclusion
    summary: str
    evidence_ids: list[str] = Field(min_length=1)
    remaining_risks: list[str]


class ActionConfirmationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    proposal: ActionProposal
    verification_status: ActionVerificationStatus
    result: dict[str, Any]
    verification_tool_calls: list[ToolCall] = Field(default_factory=list)
    recovery_assessment: Optional[RecoveryAssessment] = None
    agent_assessment_error: Optional[str] = None


class InvestigationFollowUpExchange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    response: ChatMessageResponse


class InvestigationRunStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    scenario_id: str
    status: InvestigationRunState
    response: Optional[InvestigationResponse] = None
    error: Optional[str] = None
    follow_ups: list[InvestigationFollowUpExchange] = Field(default_factory=list)
    action_result: Optional[ActionConfirmationResponse] = None

    @model_validator(mode="after")
    def validate_state_payload(self) -> InvestigationRunStatus:
        if self.status == "completed" and self.response is None:
            raise ValueError("completed investigation requires response")
        if self.status != "completed" and self.response is not None:
            raise ValueError("only completed investigation may include response")
        if self.status == "failed" and not self.error:
            raise ValueError("failed investigation requires error")
        if self.status != "failed" and self.error is not None:
            raise ValueError("only failed investigation may include error")
        if self.status != "completed" and self.follow_ups:
            raise ValueError("only completed investigation may include follow-ups")
        if self.status != "completed" and self.action_result is not None:
            raise ValueError("only completed investigation may include an action result")
        if (
            self.action_result is not None
            and self.action_result.proposal.status != "executed"
        ):
            raise ValueError("action result requires an executed proposal")
        return self


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str


class ComparisonSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparison_id: str
    scenario_id: str
    incident_id: str
    incident_title: str
    created_at: str


class ComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparison_id: str
    scenario_id: str
    baseline: InvestigationResponse
    candidate: InvestigationResponse
