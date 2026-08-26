import { describe, expect, it } from "vitest";
import type {
  ActionConfirmationResponse,
  ActionProposal,
  ChatMessageResponse,
  InvestigationEvent,
  InvestigationResponse,
  InvestigationRunStatus
} from "./api/contracts";
import {
  appendInvestigationEvent,
  formatElapsedTime,
  hydrateCompletedRun,
  latestActionProposal,
  visibleInvestigationEvents
} from "./workspaceState";

describe("comparison progress time", () => {
  it("formats elapsed seconds without exposing fractional or negative time", () => {
    expect(formatElapsedTime(0)).toBe("00:00");
    expect(formatElapsedTime(65.8)).toBe("01:05");
    expect(formatElapsedTime(-2)).toBe("00:00");
  });
});

const proposal: ActionProposal = {
  id: "proposal-1",
  action_name: "rollback_configuration",
  arguments: {
    service: "checkout",
    config_key: "db.max_open_connections",
    from_value: 80,
    to_value: 20
  },
  expected_impact: "Restore the previous pool limit.",
  requires_confirmation: true,
  status: "proposed"
};

function response(actionProposal: ActionProposal | null): ChatMessageResponse {
  return { run_id: "run-1", message: "response", evidence_ids: [], tool_calls: [], action_proposal: actionProposal };
}

describe("latestActionProposal", () => {
  it("retains a pending proposal across later chat responses without proposals", () => {
    expect(latestActionProposal(null, [response(proposal), response(null)])).toEqual(proposal);
  });

  it("retains an investigation proposal when chat returns no replacement", () => {
    expect(latestActionProposal(proposal, [response(null)])).toEqual(proposal);
  });

  it("suppresses stale proposals after an action result has been executed", () => {
    expect(latestActionProposal(proposal, [response(proposal)], executedActionResult)).toBeNull();
  });
});

const executedActionResult: ActionConfirmationResponse = {
  run_id: "run-1",
  proposal: { ...proposal, status: "executed" },
  verification_status: "verified",
  result: { replay_state: "mitigated" },
  verification_tool_calls: [],
  recovery_assessment: {
    conclusion: "recovered",
    summary: "Checkout latency recovered after the confirmed rollback.",
    evidence_ids: ["metric_checkout_latency_recovered"],
    remaining_risks: []
  },
  agent_assessment_error: null
};

describe("completed run hydration", () => {
  const run = { run_id: "run-1" } as InvestigationResponse;
  const followUps = [{
    question: "Why is payments not the cause?",
    response: response(null)
  }];

  it("restores the persisted transcript and executed verification from one GET snapshot", () => {
    const snapshot: InvestigationRunStatus = {
      run_id: "run-1",
      scenario_id: "checkout_latency_spike",
      status: "completed",
      response: run,
      error: null,
      follow_ups: followUps,
      action_result: executedActionResult
    };

    expect(hydrateCompletedRun(snapshot)).toEqual({
      run,
      followUps,
      actionResult: executedActionResult
    });
  });

  it("does not hydrate incomplete run envelopes", () => {
    const snapshot: InvestigationRunStatus = {
      run_id: "run-1",
      scenario_id: "checkout_latency_spike",
      status: "running",
      response: null,
      error: null,
      follow_ups: [],
      action_result: null
    };

    expect(hydrateCompletedRun(snapshot)).toBeNull();
  });
});

const started: InvestigationEvent = {
  id: 1,
  run_id: "run-1",
  type: "tool.started",
  created_at: "2026-08-25T12:00:00Z",
  summary: "Checking checkout health",
  payload: { sequence: 1, tool_name: "get_service_health", purpose: "Check the affected service" }
};

const completed: InvestigationEvent = {
  id: 2,
  run_id: "run-1",
  type: "tool.completed",
  created_at: "2026-08-25T12:00:01Z",
  summary: "Checkout is degraded",
  payload: {
    tool_call: {
      sequence: 1,
      tool_name: "get_service_health",
      purpose: "Check the affected service",
      arguments: { service: "checkout" },
      result: { status: "critical" },
      evidence_ids: ["health_checkout"],
      status: "ok",
      duration_ms: 23
    }
  }
};

describe("investigation event state", () => {
  it("orders replayed events and de-duplicates by durable event ID", () => {
    const events = appendInvestigationEvent(appendInvestigationEvent([], completed), started);
    expect(events.map((event) => event.id)).toEqual([1, 2]);
    expect(appendInvestigationEvent(events, completed)).toBe(events);
  });

  it("replaces a live tool-start row with its completed tool row", () => {
    expect(visibleInvestigationEvents([started, completed])).toEqual([completed]);
  });
});
