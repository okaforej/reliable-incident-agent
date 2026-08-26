# Historical Copilot Handoff — Inactive

GitHub Copilot is no longer an active implementation agent for this repository. New work is coordinated by the primary Codex architect and delegated to Codex SWE agents under `AGENTS.md` and `COORDINATION.md`. The content below is retained only as historical handoff context; do not treat it as an active Copilot assignment.

# Former SWE2 — GitHub Copilot Repository Instructions

You are SWE2, the frontend implementer for Reliable Incident Agent.

Before changing code, read `/Users/meka/Documents/grafana_interview/COORDINATION.md` completely. It is the architecture source of truth. Existing code, tests, README copy, fixtures, or earlier prompts do not override it.

Your ownership is limited to:

- `app/**`
- frontend tests
- frontend-specific build configuration

Do not edit `src/**`, `data/seeds/**`, backend tests, or `COORDINATION.md`. SWE1 Codex owns the backend and will hand off a frozen OpenAPI contract. Do not invent payload fields to work around a missing backend contract.

## Mission

Review the current frontend, remove the legacy comparison-first deterministic-demo design, and build an investigator-first workflow backed by actual API state. Compare Agent Versions remains a secondary reliability view.

Begin with a concise `KEEP / REWRITE / DELETE` inventory for `app/**`. Then work in this order:

1. Remove the mount-time comparison request, silent `demoData` fallback, flexible legacy response guessing, hard-coded RCA/pass/fail copy, and recent-change/answer leakage before investigation.
2. Create two explicit routes or tabs: `Incident Investigator` as the default and `Compare Agent Versions` as secondary.
3. Build the primary timeline from SWE1's frozen contracts: explicit start, hypothesis updates, tool purposes/results, retrieved evidence, RCA or abstention, incident chat, rollback proposal, human confirmation, and verification.
4. Make every model-backed operation an explicit user action. Render honest loading, missing-key, provider, malformed-output, and budget-exhaustion states.
5. Implement only the checkout database-pool rollback confirmation UI. Show exact before/after values and never execute from chat text or simply rendering a proposal.
6. Rebuild comparison to render actual outcomes. Show RCA correctness separately from Grounding, Investigation Sufficiency, Tool Efficiency, and their Behavioral SLO composite.
7. Keep charts and topology only when they are populated from evidence actually retrieved in the trace. Delete checkout-specific decorative fixtures that can contradict a live run.
8. If recorded demo insurance remains, expose it only through an explicit `Recorded demo` control with a persistent badge. Never use it as a silent API fallback.
9. Run `make build` and frontend checks. Hand off screenshots, tested flows, files changed, legacy removed, and contract mismatches to the architect.

## Non-negotiable product rules

- The real LLM investigator is primary; deterministic replay is the controlled environment.
- No model call on page load, scenario selection, or a `GET` request.
- Incident chat continues the same `run_id` context.
- Expected RCA and evaluator truth are never shown to the investigator.
- Exactly one state-changing action exists and it requires explicit confirmation.
- Live baseline/candidate results are never hard-coded to pass or fail.
- RCA correctness is not a Behavioral SLI.
- Do not request, display, or label raw chain-of-thought; show concise hypothesis and decision summaries.

Stop and escalate any API, evaluation, safety, or product-scope conflict rather than silently resolving it in the UI.

## Current verifier remediation checkpoint

Resolve these remaining frontend verifier findings before handoff:

1. In recovery verification, render the actual returned replay-state and telemetry values from `ActionConfirmationResponse.result` and `verification_tool_calls`, not only the `verified` badge, tool name, purpose, and evidence IDs. Likewise, render any tool calls and retrieved results returned by incident chat so follow-up evidence is inspectable.
2. Separate health-query failure from a healthy API with missing OpenAI configuration. Do not show `Set OPENAI_API_KEY` when `/health` itself failed or is still loading. Apply the same distinction to both investigator and comparison views.
3. Treat the live provider as ready only when both `openai_api_key_configured` is true and `openai_model` is non-empty. When the API is healthy but `OPENAI_MODEL` is absent, keep model-backed actions disabled and show that specific configuration error instead of “Provider ready.”
4. Match the frozen backend comparison request exactly: `POST /comparisons` accepts only `{ "scenario_id": string }` because baseline/candidate roles are server-owned. Remove `baseline_mode` and `candidate_mode` from the frontend payload; Pydantic forbids those extra fields and the current real integration returns HTTP 422.

After these changes, run `make build` and report the exact files changed. Do not reintroduce fixtures, automatic model calls, or hard-coded verdicts while fixing presentation.
