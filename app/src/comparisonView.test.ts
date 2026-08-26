import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ComparisonRunningState } from "./Workspace";
import type { ScenarioSummary } from "./api/contracts";

const scenario: ScenarioSummary = {
  id: "checkout_latency_spike",
  name: "Checkout Latency Spike",
  incident_id: "inc_checkout_001",
  severity: "SEV2",
  status: "active",
  affected_service: "checkout",
  started_at: "2026-08-24T09:12:00Z",
  customer_impact: "Checkout latency increased.",
  target_sli: "Checkout latency below 500 ms.",
  symptoms: []
};

describe("comparison running state", () => {
  it("shows honest in-flight feedback for both agent lanes", () => {
    const html = renderToStaticMarkup(createElement(ComparisonRunningState, {
      scenario,
      elapsedSeconds: 65
    }));

    expect(html).toContain("Comparison in progress");
    expect(html).toContain("Checkout Latency Spike");
    expect(html).toContain("01:05");
    expect(html).toContain("Baseline");
    expect(html).toContain("Candidate");
    expect(html).toContain("Both results load together");
    expect(html).not.toContain("tool.started");
  });
});
