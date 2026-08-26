import type { Health } from "./api/contracts";

export type ProviderAvailability =
  | { kind: "loading"; ready: false; label: string }
  | { kind: "api_unavailable"; ready: false; label: string; detail: string }
  | { kind: "api_unhealthy"; ready: false; label: string; detail: string }
  | { kind: "key_missing"; ready: false; label: string }
  | { kind: "model_missing"; ready: false; label: string }
  | { kind: "ready"; ready: true; label: string; model: string };

export type HealthQuerySnapshot = {
  isPending: boolean;
  isError: boolean;
  data?: Health;
  error?: unknown;
};

export function getProviderAvailability(snapshot: HealthQuerySnapshot): ProviderAvailability {
  if (snapshot.isError) {
    return {
      kind: "api_unavailable",
      ready: false,
      label: "API unavailable",
      detail: readableError(snapshot.error)
    };
  }
  if (snapshot.isPending) {
    return { kind: "loading", ready: false, label: "Checking provider" };
  }
  if (!snapshot.data || snapshot.data.status !== "ok") {
    return {
      kind: "api_unhealthy",
      ready: false,
      label: "API unhealthy",
      detail: snapshot.data?.status
        ? `Health status was ${snapshot.data.status}.`
        : "The health response was missing."
    };
  }
  if (!snapshot.data.openai_api_key_configured) {
    return { kind: "key_missing", ready: false, label: "OpenAI key missing" };
  }
  const model = snapshot.data.openai_model?.trim();
  if (!model) {
    return { kind: "model_missing", ready: false, label: "OpenAI model missing" };
  }
  return { kind: "ready", ready: true, label: model, model };
}

export function unavailableMessage(
  availability: Exclude<ProviderAvailability, { kind: "ready" }>,
  operation: "investigation" | "comparison"
): string {
  const action = operation === "investigation" ? "start a live investigation" : "run a live comparison";
  switch (availability.kind) {
    case "loading":
      return "Checking live provider…";
    case "api_unavailable":
      return `API unavailable: ${availability.detail}`;
    case "api_unhealthy":
      return `API unhealthy: ${availability.detail}`;
    case "key_missing":
      return `Set OPENAI_API_KEY to ${action}. Live results only.`;
    case "model_missing":
      return `Set OPENAI_MODEL to ${action}.`;
  }
}

function readableError(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected request failure.";
}
