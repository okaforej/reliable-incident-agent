import type {
  ActionConfirmationResponse,
  ActionProposal,
  ChatMessageResponse,
  InvestigationEvent,
  InvestigationFollowUpExchange,
  InvestigationResponse,
  InvestigationRunStatus
} from "./api/contracts";

export function latestActionProposal(
  initial: ActionProposal | null,
  responses: ChatMessageResponse[],
  actionResult: ActionConfirmationResponse | null = null
): ActionProposal | null {
  if (actionResult) return null;
  return responses.reduce(
    (latest, response) => response.action_proposal ?? latest,
    initial
  );
}

export type CompletedRunHydration = {
  run: InvestigationResponse;
  followUps: InvestigationFollowUpExchange[];
  actionResult: ActionConfirmationResponse | null;
};

export function hydrateCompletedRun(
  snapshot: InvestigationRunStatus
): CompletedRunHydration | null {
  if (snapshot.status !== "completed") return null;
  return {
    run: snapshot.response,
    followUps: snapshot.follow_ups,
    actionResult: snapshot.action_result
  };
}

export function appendInvestigationEvent(
  events: InvestigationEvent[],
  next: InvestigationEvent
): InvestigationEvent[] {
  if (events.some((event) => event.id === next.id)) return events;
  return [...events, next].sort((left, right) => left.id - right.id);
}

export function visibleInvestigationEvents(events: InvestigationEvent[]): InvestigationEvent[] {
  const completedSequences = new Set(
    events
      .filter((event) => event.type === "tool.completed")
      .map((event) => event.payload.tool_call.sequence)
  );
  return events.filter(
    (event) => event.type !== "tool.started" || !completedSequences.has(event.payload.sequence)
  );
}

export function formatElapsedTime(seconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(safeSeconds / 60)).padStart(2, "0")}:${String(safeSeconds % 60).padStart(2, "0")}`;
}
