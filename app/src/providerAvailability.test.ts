import { describe, expect, it } from "vitest";
import { getProviderAvailability, unavailableMessage } from "./providerAvailability";

const healthy = {
  status: "ok",
  openai_api_key_configured: true,
  openai_model: "gpt-tool-model"
};

describe("getProviderAvailability", () => {
  it("keeps live actions disabled while health is loading", () => {
    expect(getProviderAvailability({ isPending: true, isError: false }).kind).toBe("loading");
  });

  it("separates an API failure from provider configuration", () => {
    const state = getProviderAvailability({ isPending: false, isError: true, error: new Error("offline") });
    expect(state).toMatchObject({ kind: "api_unavailable", ready: false, detail: "offline" });
    if (!state.ready) expect(unavailableMessage(state, "investigation")).not.toContain("OPENAI_API_KEY");
  });

  it("rejects an unhealthy response", () => {
    expect(getProviderAvailability({ isPending: false, isError: false, data: { ...healthy, status: "degraded" } }).kind).toBe("api_unhealthy");
  });

  it("distinguishes a missing API key", () => {
    expect(getProviderAvailability({ isPending: false, isError: false, data: { ...healthy, openai_api_key_configured: false } }).kind).toBe("key_missing");
  });

  it("requires a non-empty model", () => {
    expect(getProviderAvailability({ isPending: false, isError: false, data: { ...healthy, openai_model: "  " } }).kind).toBe("model_missing");
  });

  it("is ready only when health, key, and model all pass", () => {
    expect(getProviderAvailability({ isPending: false, isError: false, data: healthy })).toEqual({ kind: "ready", ready: true, label: "gpt-tool-model", model: "gpt-tool-model" });
  });
});
