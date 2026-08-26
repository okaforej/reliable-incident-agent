"""Pydantic contracts shared by runtime, API, UI, and evaluator."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)


class InvestigationTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    incident_description: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
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
    mode: Literal["baseline", "candidate"]


class InvestigationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    trace: InvestigationTrace
    evaluation: BehavioralEvaluation


class ScenarioSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    incident_id: str
    severity: str
    affected_service: str


class ScenarioDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    incident: dict[str, Any]
    services: list[dict[str, Any]]
    dependencies: list[dict[str, Any]]
    changes: list[dict[str, Any]]


class ScenarioEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    metrics: list[dict[str, Any]]
    logs: list[dict[str, Any]]
    changes: list[dict[str, Any]]
    dependencies: list[dict[str, Any]]


class ComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    baseline: InvestigationResponse
    candidate: InvestigationResponse
