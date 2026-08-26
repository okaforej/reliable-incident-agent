export type AgentMode = "weak" | "reliable";

export type Scenario = {
  id: string;
  name: string;
  description: string;
  severity: string;
  timeWindow: string;
  affectedServices: string[];
  recentChanges: string[];
};

export type ToolCall = {
  sequence: number;
  toolName: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
};

export type InvestigationTrace = {
  incidentId: string;
  incidentDescription: string;
  toolCalls: ToolCall[];
  finalRootCause: string;
};

export type BehavioralEvaluation = {
  rcaCorrect: boolean;
  grounded: boolean;
  investigationSufficient: boolean;
  toolEfficient: boolean;
  behavioralSloPass: boolean;
  reasons: string[];
};

export type InvestigationRun = {
  mode: AgentMode;
  runId: string;
  trace: InvestigationTrace;
  evaluation: BehavioralEvaluation;
};

export type Comparison = {
  scenarioId: string;
  weak: InvestigationRun;
  reliable: InvestigationRun;
};

export type EvidencePoint = {
  timestamp: string;
  checkoutLatencyMs: number;
  checkoutErrorRate: number;
  postgresConnections: number;
  paymentLatencyMs: number;
};

export type ServiceNode = {
  id: string;
  label: string;
  status: "healthy" | "degraded" | "saturated" | "collateral";
};

export type ServiceEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
};
