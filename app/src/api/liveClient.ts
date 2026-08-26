import type {
  ActionConfirmationResponse,
  AgentMode,
  ChatMessageResponse,
  ComparisonResponse,
  ComparisonSummary,
  Health,
  InvestigationAccepted,
  InvestigationEvent,
  InvestigationResponse,
  InvestigationRunStatus,
  InvestigationSummary,
  ScenarioDetail,
  ScenarioSummary
} from "./contracts";

const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api";

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init?.headers }
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as unknown;
    throw new ApiError(response.status, apiErrorMessage(payload, response.status, response.statusText));
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/health"),
  scenarios: () => request<ScenarioSummary[]>("/scenarios"),
  scenario: (scenarioId: string) => request<ScenarioDetail>(`/scenarios/${encodeURIComponent(scenarioId)}`),
  listInvestigations: () => request<InvestigationSummary[]>("/investigations"),
  startInvestigation: (scenarioId: string, mode: AgentMode = "candidate") =>
    request<InvestigationAccepted>("/investigations", {
      method: "POST",
      body: JSON.stringify({ scenario_id: scenarioId, mode, live: true })
    }),
  getInvestigation: (runId: string) =>
    request<InvestigationRunStatus>(`/investigations/${encodeURIComponent(runId)}`),
  sendMessage: (runId: string, message: string) =>
    request<ChatMessageResponse>(`/investigations/${encodeURIComponent(runId)}/messages`, {
      method: "POST",
      body: JSON.stringify({ message })
    }),
  confirmAction: (runId: string, proposalId: string) =>
    request<ActionConfirmationResponse>(
      `/investigations/${encodeURIComponent(runId)}/actions/${encodeURIComponent(proposalId)}/confirm`,
      { method: "POST" }
    ),
  listComparisons: () => request<ComparisonSummary[]>("/comparisons"),
  startComparison: (scenarioId: string) =>
    request<ComparisonResponse>("/comparisons", {
      method: "POST",
      body: JSON.stringify({ scenario_id: scenarioId })
    }),
  getComparison: (comparisonId: string) =>
    request<ComparisonResponse>(`/comparisons/${encodeURIComponent(comparisonId)}`),
  investigationEventsUrl: (runId: string) =>
    `${apiBase}/investigations/${encodeURIComponent(runId)}/events`
};

export const investigationEventTypes: InvestigationEvent["type"][] = [
  "investigation.started",
  "hypotheses.updated",
  "tool.started",
  "tool.completed",
  "investigation.completed",
  "investigation.failed"
];

export type InvestigationStreamHandlers = {
  onOpen: () => void;
  onEvent: (event: InvestigationEvent) => void;
  onDisconnect: () => void;
  onMalformedEvent: (error: Error) => void;
};

export function subscribeToInvestigationEvents(
  runId: string,
  handlers: InvestigationStreamHandlers,
  createSource: (url: string) => EventSource = (url) => new EventSource(url)
): () => void {
  const source = createSource(api.investigationEventsUrl(runId));
  source.onopen = handlers.onOpen;
  source.onerror = handlers.onDisconnect;
  const listeners = investigationEventTypes.map((type) => {
    const listener = (message: Event) => {
      try {
        const event = parseInvestigationEvent((message as MessageEvent<string>).data);
        if (event.type !== type) throw new Error(`SSE event type mismatch: expected ${type}`);
        if (event.run_id !== runId) throw new Error("The progress stream returned an event for a different investigation.");
        handlers.onEvent(event);
        if (event.type === "investigation.completed" || event.type === "investigation.failed") {
          source.close();
        }
      } catch (error) {
        source.close();
        handlers.onMalformedEvent(error instanceof Error ? error : new Error("Malformed investigation event"));
      }
    };
    source.addEventListener(type, listener);
    return [type, listener] as const;
  });
  return () => {
    listeners.forEach(([type, listener]) => source.removeEventListener(type, listener));
    source.close();
  };
}

export function parseInvestigationEvent(data: string): InvestigationEvent {
  const value = JSON.parse(data) as unknown;
  if (!isRecord(value)
    || !Number.isInteger(value.id)
    || typeof value.run_id !== "string"
    || !investigationEventTypes.includes(value.type as InvestigationEvent["type"])
    || typeof value.created_at !== "string"
    || typeof value.summary !== "string"
    || !isRecord(value.payload)
    || !isInvestigationEventPayload(value.type as InvestigationEvent["type"], value.payload)) {
    throw new Error("The API returned a malformed investigation progress event.");
  }
  return value as InvestigationEvent;
}

function isInvestigationEventPayload(
  type: InvestigationEvent["type"],
  payload: Record<string, unknown>
): boolean {
  switch (type) {
    case "investigation.started":
      return typeof payload.scenario_id === "string"
        && typeof payload.incident_id === "string"
        && (payload.agent_config_id === "baseline" || payload.agent_config_id === "candidate");
    case "hypotheses.updated":
      return Array.isArray(payload.hypotheses) && payload.hypotheses.every(isHypothesisFinding);
    case "tool.started":
      return isPositiveInteger(payload.sequence)
        && typeof payload.tool_name === "string"
        && typeof payload.purpose === "string";
    case "tool.completed":
      return isToolCall(payload.tool_call);
    case "investigation.completed":
      return Number.isInteger(payload.tool_call_count) && Number(payload.tool_call_count) >= 0;
    case "investigation.failed":
      return typeof payload.error === "string" && payload.error.length > 0;
  }
}

function isHypothesisFinding(value: unknown): boolean {
  return isRecord(value)
    && typeof value.hypothesis === "string"
    && (value.status === "supported" || value.status === "weakened" || value.status === "unresolved")
    && isStringArray(value.evidence_ids);
}

function isToolCall(value: unknown): boolean {
  return isRecord(value)
    && isPositiveInteger(value.sequence)
    && typeof value.tool_name === "string"
    && typeof value.purpose === "string"
    && isRecord(value.arguments)
    && isRecord(value.result)
    && isStringArray(value.evidence_ids)
    && (value.status === "ok" || value.status === "error")
    && typeof value.duration_ms === "number"
    && Number.isFinite(value.duration_ms)
    && value.duration_ms >= 0;
}

function isPositiveInteger(value: unknown): boolean {
  return Number.isInteger(value) && Number(value) >= 1;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected request failure";
}

export function apiErrorMessage(payload: unknown, status: number, statusText: string): string {
  const fallback = `${status} ${statusText}`.trim();
  if (!isRecord(payload) || !("detail" in payload)) return fallback;
  const { detail } = payload;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const issues = detail.map(validationIssue).filter((issue): issue is string => Boolean(issue));
    if (issues.length) return issues.join("; ");
  }
  return fallback;
}

function validationIssue(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value;
  if (!isRecord(value) || typeof value.msg !== "string" || !value.msg.trim()) return null;
  const location = Array.isArray(value.loc)
    ? value.loc.filter((part) => typeof part === "string" || typeof part === "number").join(".")
    : "";
  return location ? `${location}: ${value.msg}` : value.msg;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
