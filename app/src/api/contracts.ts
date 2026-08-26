export type AgentMode = "baseline" | "candidate";
export type Outcome = "root_cause" | "abstain" | "error";
export type Confidence = "low" | "medium" | "high";

export type Health = {
  status: string;
  openai_api_key_configured: boolean;
  openai_model: string | null;
};

export type ScenarioSummary = {
  id: string;
  name: string;
  incident_id: string;
  severity: string;
  status: "active";
  affected_service: string;
  started_at: string;
  customer_impact: string;
  target_sli: string;
  symptoms: string[];
};

export type InvestigationSummary = {
  run_id: string;
  scenario_id: string;
  incident_id: string;
  incident_title: string;
  status: "queued" | "running" | "completed" | "failed";
  outcome: Outcome | null;
  created_at: string;
  updated_at: string;
};

export type ScenarioDetail = {
  id: string;
  name: string;
  incident: Record<string, unknown>;
  services: Array<Record<string, unknown>>;
};

export type ToolCall = {
  sequence: number;
  tool_name: string;
  purpose: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
  evidence_ids: string[];
  status: "ok" | "error";
  duration_ms: number;
};

export type HypothesisFinding = {
  hypothesis: string;
  status: "supported" | "weakened" | "unresolved";
  evidence_ids: string[];
};

export type ActionProposal = {
  id: string;
  action_name: "rollback_configuration";
  arguments: Record<string, unknown>;
  expected_impact: string;
  requires_confirmation: boolean;
  status: "proposed" | "executed" | "rejected";
};

export type InvestigationFinalResult = {
  outcome: Outcome;
  root_cause: string | null;
  confidence: Confidence;
  evidence_ids: string[];
  hypothesis_summary: HypothesisFinding[];
  mitigation: string | null;
  verification_plan: string[];
  missing_evidence: string[];
  action_proposal: ActionProposal | null;
};

export type InvestigationTrace = {
  incident_id: string;
  incident_description: string;
  agent_config_id: AgentMode;
  prompt_version: string;
  tool_schema_version: string;
  model: string;
  hypotheses: string[];
  tool_calls: ToolCall[];
  final_result: InvestigationFinalResult;
  provider_metadata: {
    provider: string;
    model: string;
    response_ids: string[];
    input_tokens: number | null;
    output_tokens: number | null;
    latency_ms: number | null;
  };
  final_root_cause: string;
};

export type BehavioralEvaluation = {
  rca_correct: boolean;
  grounded: boolean;
  investigation_sufficient: boolean;
  tool_efficient: boolean;
  behavioral_slo_pass: boolean;
  reasons: string[];
};

export type InvestigationResponse = {
  run_id: string;
  trace: InvestigationTrace;
  evaluation: BehavioralEvaluation | null;
};

export type InvestigationAccepted = {
  run_id: string;
  scenario_id: string;
  status: "queued" | "running";
};

type InvestigationRunStatusEnvelope = {
  run_id: string;
  scenario_id: string;
  follow_ups: InvestigationFollowUpExchange[];
  action_result: ActionConfirmationResponse | null;
};

export type InvestigationRunStatus = InvestigationRunStatusEnvelope & (
  | { status: "queued" | "running"; response: null; error: null }
  | { status: "completed"; response: InvestigationResponse; error: null }
  | { status: "failed"; response: null; error: string }
);

type InvestigationEventEnvelope<
  Type extends string,
  Payload extends Record<string, unknown>
> = {
  id: number;
  run_id: string;
  type: Type;
  created_at: string;
  summary: string;
  payload: Payload;
};

export type InvestigationEvent =
  | InvestigationEventEnvelope<
      "investigation.started",
      { scenario_id: string; incident_id: string; agent_config_id: AgentMode }
    >
  | InvestigationEventEnvelope<
      "hypotheses.updated",
      { hypotheses: HypothesisFinding[] }
    >
  | InvestigationEventEnvelope<
      "tool.started",
      { sequence: number; tool_name: string; purpose: string }
    >
  | InvestigationEventEnvelope<"tool.completed", { tool_call: ToolCall }>
  | InvestigationEventEnvelope<
      "investigation.completed",
      { tool_call_count: number }
    >
  | InvestigationEventEnvelope<"investigation.failed", { error: string }>;

export type ChatMessageResponse = {
  run_id: string;
  message: string;
  evidence_ids: string[];
  tool_calls: ToolCall[];
  action_proposal: ActionProposal | null;
};

export type InvestigationFollowUpExchange = {
  question: string;
  response: ChatMessageResponse;
};

export type RecoveryAssessment = {
  conclusion: "recovered" | "not_recovered" | "uncertain";
  summary: string;
  evidence_ids: string[];
  remaining_risks: string[];
};

export type ActionConfirmationResponse = {
  run_id: string;
  proposal: ActionProposal;
  verification_status: "pending" | "verified" | "not_verified";
  result: Record<string, unknown>;
  verification_tool_calls: ToolCall[];
  recovery_assessment: RecoveryAssessment | null;
  agent_assessment_error: string | null;
};

export type ComparisonResponse = {
  comparison_id: string;
  scenario_id: string;
  baseline: InvestigationResponse;
  candidate: InvestigationResponse;
};

export type ComparisonSummary = {
  comparison_id: string;
  scenario_id: string;
  incident_id: string;
  incident_title: string;
  created_at: string;
};
