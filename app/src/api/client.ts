import { demoComparison, demoScenarios } from "./demoData";
import type {
  AgentMode,
  BehavioralEvaluation,
  Comparison,
  InvestigationRun,
  InvestigationTrace,
  Scenario,
  ToolCall
} from "./types";

const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    headers: { Accept: "application/json" }
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export async function getScenarios(): Promise<Scenario[]> {
  const payload = await fetchJson<unknown>("/scenarios");
  return normalizeScenarios(payload);
}

export async function getComparison(scenarioId: string): Promise<Comparison> {
  const payload = await fetchJson<unknown>(`/comparisons/${encodeURIComponent(scenarioId)}`);
  return normalizeComparison(payload, scenarioId);
}

export function scenariosWithFallback(data: Scenario[] | undefined): Scenario[] {
  return data && data.length > 0 ? data : demoScenarios;
}

export function comparisonWithFallback(data: Comparison | undefined, scenarioId: string): Comparison {
  if (data) {
    return data;
  }

  return { ...demoComparison, scenarioId };
}

function normalizeScenarios(payload: unknown): Scenario[] {
  const items = Array.isArray(payload)
    ? payload
    : getRecord(payload).scenarios && Array.isArray(getRecord(payload).scenarios)
      ? (getRecord(payload).scenarios as unknown[])
      : [];

  return items.map((item) => {
    const record = getRecord(item);
    const id = stringValue(record.scenario_id ?? record.id, demoScenarios[0].id);
    const affected = record.affected_services ?? record.affectedServices ?? record.services ?? record.affected_service;
    const recentChanges = record.recent_changes ?? record.recentChanges ?? record.changes;

    return {
      id,
      name: stringValue(record.name ?? record.title, humanize(id)),
      description: stringValue(record.description ?? record.summary, demoScenarios[0].description),
      severity: stringValue(record.severity, demoScenarios[0].severity),
      timeWindow: normalizeTimeWindow(record.time_window ?? record.timeWindow ?? record.window),
      affectedServices: stringArray(affected, demoScenarios[0].affectedServices),
      recentChanges: stringArray(recentChanges, demoScenarios[0].recentChanges)
    };
  });
}

function normalizeComparison(payload: unknown, scenarioId: string): Comparison {
  const record = getRecord(payload);
  const comparisonRecord = getRecord(record.comparison);
  const baselinePayload =
    record.baseline ??
    record.baseline_run ??
    record.baselineRun ??
    record.baselineInvestigation ??
    record.version_a ??
    record.versionA ??
    comparisonRecord.baseline ??
    comparisonRecord.baseline_run ??
    comparisonRecord.baselineRun ??
    comparisonRecord.baselineInvestigation ??
    comparisonRecord.version_a ??
    comparisonRecord.versionA ??
    findRun(record.runs, ["baseline", "version_a", "versionA"]) ??
    findRun(comparisonRecord.runs, ["baseline", "version_a", "versionA"]);
  const candidatePayload =
    record.candidate ??
    record.candidate_run ??
    record.candidateRun ??
    record.candidateInvestigation ??
    record.version_b ??
    record.versionB ??
    comparisonRecord.candidate ??
    comparisonRecord.candidate_run ??
    comparisonRecord.candidateRun ??
    comparisonRecord.candidateInvestigation ??
    comparisonRecord.version_b ??
    comparisonRecord.versionB ??
    findRun(record.runs, ["candidate", "version_b", "versionB"]) ??
    findRun(comparisonRecord.runs, ["candidate", "version_b", "versionB"]);

  return {
    scenarioId: stringValue(record.scenario_id ?? record.scenarioId, scenarioId),
    baseline: normalizeRun(baselinePayload, "baseline", demoComparison.baseline),
    candidate: normalizeRun(candidatePayload, "candidate", demoComparison.candidate)
  };
}

function normalizeRun(payload: unknown, mode: AgentMode, fallback: InvestigationRun): InvestigationRun {
  const record = getRecord(payload);
  return {
    mode,
    runId: stringValue(record.run_id ?? record.runId ?? record.id, fallback.runId),
    trace: normalizeTrace(record.trace ?? payload, fallback.trace),
    evaluation: normalizeEvaluation(record.evaluation ?? record.behavioral_evaluation, fallback.evaluation)
  };
}

function normalizeTrace(payload: unknown, fallback: InvestigationTrace): InvestigationTrace {
  const record = getRecord(payload);
  const toolCalls = record.tool_calls ?? record.toolCalls ?? [];

  return {
    incidentId: stringValue(record.incident_id ?? record.incidentId, fallback.incidentId),
    incidentDescription: stringValue(
      record.incident_description ?? record.incidentDescription ?? record.description,
      fallback.incidentDescription
    ),
    toolCalls: Array.isArray(toolCalls)
      ? toolCalls.map((toolCall, index) => normalizeToolCall(toolCall, index + 1))
      : fallback.toolCalls,
    finalRootCause: stringValue(record.final_root_cause ?? record.finalRootCause ?? record.rca, fallback.finalRootCause)
  };
}

function normalizeToolCall(payload: unknown, sequenceFallback: number): ToolCall {
  const record = getRecord(payload);
  return {
    sequence: numberValue(record.sequence ?? record.seq, sequenceFallback),
    toolName: stringValue(record.tool_name ?? record.toolName ?? record.name, "tool_call"),
    arguments: getRecord(record.arguments ?? record.args ?? {}),
    result: getRecord(record.result ?? record.output ?? {})
  };
}

function normalizeEvaluation(payload: unknown, fallback: BehavioralEvaluation): BehavioralEvaluation {
  const record = getRecord(payload);

  return {
    rcaCorrect: booleanValue(record.rca_correct ?? record.rcaCorrect, fallback.rcaCorrect),
    grounded: booleanValue(record.grounded, fallback.grounded),
    investigationSufficient: booleanValue(
      record.investigation_sufficient ?? record.investigationSufficient ?? record.sufficient,
      fallback.investigationSufficient
    ),
    toolEfficient: booleanValue(record.tool_efficient ?? record.toolEfficient ?? record.efficient, fallback.toolEfficient),
    behavioralSloPass: booleanValue(
      record.behavioral_slo_pass ?? record.behavioralSloPass ?? record.slo_pass,
      fallback.behavioralSloPass
    ),
    reasons: stringArray(record.reasons, fallback.reasons)
  };
}

function findRun(payload: unknown, modes: string[]): unknown {
  if (!Array.isArray(payload)) {
    return undefined;
  }

  return payload.find((item) => modes.includes(stringValue(getRecord(item).mode, "")));
}

function getRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function stringArray(value: unknown, fallback: string[]): string[] {
  if (Array.isArray(value)) {
    const strings = value
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }

        const record = getRecord(item);
        return stringValue(record.name ?? record.service ?? record.summary ?? record.description, "");
      })
      .filter(Boolean);

    return strings.length > 0 ? strings : fallback;
  }

  if (typeof value === "string" && value.trim()) {
    return [value];
  }

  return fallback;
}

function normalizeTimeWindow(value: unknown): string {
  if (typeof value === "string" && value.trim()) {
    return value;
  }

  const record = getRecord(value);
  const start = stringValue(record.start, "");
  const end = stringValue(record.end, "");
  return start && end ? `${start}-${end}` : demoScenarios[0].timeWindow;
}

function humanize(id: string): string {
  return id
    .split(/[_-]/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}
