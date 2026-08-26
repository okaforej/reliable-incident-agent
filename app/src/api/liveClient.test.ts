import { afterEach, describe, expect, it, vi } from "vitest";
import { api, apiErrorMessage, parseInvestigationEvent } from "./liveClient";

afterEach(() => vi.unstubAllGlobals());

describe("live API contracts", () => {
  it("lists persisted investigations with a read-only request", async () => {
    const summaries = [{
      run_id: "run-1",
      scenario_id: "scenario-public-1",
      incident_id: "INC-1",
      incident_title: "Checkout latency spike",
      status: "completed",
      outcome: "root_cause",
      created_at: "2026-08-26T12:00:00Z",
      updated_at: "2026-08-26T12:01:00Z"
    }];
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(summaries), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.listInvestigations()).resolves.toEqual(summaries);
    expect(fetchMock).toHaveBeenCalledWith("/api/investigations", expect.objectContaining({
      headers: expect.objectContaining({ Accept: "application/json" })
    }));
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("method", "POST");
  });

  it("lists persisted comparisons with a read-only request", async () => {
    const summaries = [{
      comparison_id: "cmp-1",
      scenario_id: "scenario-public-1",
      incident_id: "INC-1",
      incident_title: "Checkout latency spike",
      created_at: "2026-08-26T12:00:00Z"
    }];
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(summaries), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.listComparisons()).resolves.toEqual(summaries);
    expect(fetchMock).toHaveBeenCalledWith("/api/comparisons", expect.objectContaining({
      headers: expect.objectContaining({ Accept: "application/json" })
    }));
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("method", "POST");
  });

  it("retrieves the persisted completed workspace without issuing a POST", async () => {
    const completed = {
      run_id: "run-1",
      scenario_id: "scenario-public-1",
      status: "completed",
      response: { run_id: "run-1" },
      error: null,
      follow_ups: [{
        question: "Why is payments not the cause?",
        response: { run_id: "run-1", message: "Payments remained healthy.", evidence_ids: ["health_payments"], tool_calls: [], action_proposal: null }
      }],
      action_result: { proposal: { status: "executed" }, verification_status: "verified" }
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(completed), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.getInvestigation("run-1")).resolves.toEqual(completed);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/investigations/run-1");
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("method", "POST");
  });

  it("accepts an investigation asynchronously without requesting a fixture mode", async () => {
    const accepted = { run_id: "run-1", scenario_id: "scenario-public-1", status: "queued" };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(accepted), {
      status: 202,
      headers: { "Content-Type": "application/json" }
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.startInvestigation("scenario-public-1")).resolves.toEqual(accepted);
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ scenario_id: "scenario-public-1", mode: "candidate", live: true })
    });
  });

  it("posts only the server-owned comparison scenario field", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ comparison_id: "cmp-1" }), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    }));
    vi.stubGlobal("fetch", fetchMock);

    await api.startComparison("scenario-public-1");

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/comparisons");
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ scenario_id: "scenario-public-1" })
    });
  });

  it("normalizes string FastAPI details", () => {
    expect(apiErrorMessage({ detail: "Model provider unavailable" }, 503, "Service Unavailable")).toBe("Model provider unavailable");
  });

  it("normalizes FastAPI validation issue arrays", () => {
    expect(apiErrorMessage({ detail: [{ loc: ["body", "baseline_mode"], msg: "Extra inputs are not permitted" }] }, 422, "Unprocessable Entity")).toBe("body.baseline_mode: Extra inputs are not permitted");
  });

  it("falls back safely for unknown detail shapes", () => {
    expect(apiErrorMessage({ detail: { nested: true } }, 500, "Internal Server Error")).toBe("500 Internal Server Error");
  });

  it("parses the typed SSE envelope", () => {
    expect(parseInvestigationEvent(JSON.stringify({
      id: 7,
      run_id: "run-1",
      type: "tool.started",
      created_at: "2026-08-25T12:00:00Z",
      summary: "Checking service health",
      payload: { sequence: 1, tool_name: "get_service_health", purpose: "Check the affected service" }
    }))).toMatchObject({ id: 7, type: "tool.started" });
  });

  it("rejects malformed SSE envelopes instead of guessing", () => {
    expect(() => parseInvestigationEvent(JSON.stringify({ id: "seven", type: "tool.started" })))
      .toThrow("malformed investigation progress event");
  });

  it("rejects a valid envelope whose typed payload is incomplete", () => {
    expect(() => parseInvestigationEvent(JSON.stringify({
      id: 8,
      run_id: "run-1",
      type: "tool.completed",
      created_at: "2026-08-25T12:00:01Z",
      summary: "Tool finished",
      payload: { tool_name: "get_service_health" }
    }))).toThrow("malformed investigation progress event");
  });
});
