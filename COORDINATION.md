# Reliable Incident Agent — Architecture and Execution Contract

Status: architecture source of truth
Owner: Architect / coordinator (primary Codex task)
Implementers: Codex SWE agents assigned per workstream

This document replaces the legacy deterministic-investigator plan. If existing code, tests, README text, fixtures, or earlier handoffs conflict with this document, this document wins.

## 1. North Star

> **One real LLM autonomously investigates a deterministic incident replay using realistic observability tools.**

The product has two nested surfaces:

1. **Primary — AI Incident Investigator:** an on-call engineer gives a real LLM an incident, watches it form and test hypotheses through observability tools, asks evidence-grounded follow-up questions, confirms one safe simulated rollback, and sees both deterministic recovery verification and the investigator's evidence-backed assessment.
2. **Secondary — Compare Agent Versions:** an AI/reliability engineer runs two legitimate agent configurations against the same replay and evaluates their trajectories with Behavioral SLOs.

The product answers:

```text
Can AI help investigate and resolve this incident?
                    ↓
Can we measure whether that AI remains reliable as its configuration changes?
```

## 2. Product Thesis and Hiring Story

The deterministic replay is the controlled experiment. The LLM investigator is the system under evaluation.

```text
DETERMINISTIC                              NON-DETERMINISTIC
Incident replay                           Real LLM investigator
SQLite evidence                           Hypothesis formation
Observability tool results                Adaptive tool selection
Action state transition                   Evidence interpretation
Expected outcome                          RCA or abstention
Behavioral evaluator                      Remediation proposal
```

This demonstrates applied AI engineering through prompt/context design, semantic tool contracts, adaptive function calling, evidence-grounded synthesis, abstention, conversational continuation, and evaluation of nondeterministic behavior. It demonstrates Staff-level thinking by adding a reliability and release-decision layer around the agent rather than treating one plausible answer as proof of quality.

## 3. Product Guardrails

- The primary path **must use a real OpenAI-backed LLM**. A scripted Python trajectory or constant RCA is not a valid primary implementation.
- Use the OpenAI Responses API with custom function tools behind an injected provider interface. Credentials come only from `OPENAI_API_KEY`; the selected tool-capable model comes from `OPENAI_MODEL`.
- The investigator initially receives only agent-safe incident context and tool definitions. It must not receive scenario descriptions containing the cause, complete telemetry, expected outcomes, evaluator rules, or preselected tool sequences.
- Baseline and candidate use the same model, model settings, replay, tool schemas, and available evidence. Their principal experimental difference is the investigation prompt/context policy.
- The model chooses which read tools to call, in what order, and when to stop within a fixed budget.
- Expected RCA is loaded only after a trace has completed and only by the evaluator.
- Core evaluation remains deterministic for the MVP. An LLM judge is stretch work and must not become a dependency for the primary demo.
- No raw chain-of-thought is requested, persisted, or displayed. Store concise hypothesis updates, tool purposes, evidence references, and decision summaries.
- Live execution is explicit. No model call occurs on page load, scenario selection, or a `GET` request.
- Missing credentials or live-model failures are shown clearly. The UI must never silently substitute hard-coded success data.
- A labelled, manually selected recorded run may exist as emergency demo insurance, but it must be visibly distinct from the live primary path.
- Exactly one simulated state-changing capability is in scope: rollback of the checkout database-pool configuration. It always requires explicit human confirmation.
- Every investigation receives an isolated replay instance. A confirmed action may mutate only that run's instance; later investigations and comparison arms must start from independent active snapshots.

## 4. Primary User Flow

```text
Select an incident
        ↓
Review agent-safe alert context
        ↓
See `Replay environment · deterministic telemetry`
        ↓
Click Investigate incident
        ↓
Real LLM forms competing hypotheses
        ↓
LLM adaptively invokes observability tools
        ↓
UI streams concise progress, tool purposes/results, evidence, and hypothesis updates
        ↓
LLM returns RCA or abstains, with evidence and missing evidence
        ↓
On-call engineer asks a follow-up in the same investigation context
        ↓
LLM proposes the single supported configuration rollback
        ↓
Human reviews and explicitly confirms
        ↓
Replay state changes from active to mitigated
        ↓
Application code verifies returned recovery telemetry
        ↓
Same investigation context explains the recovery evidence
```

Primary user: on-call / operations engineer.
Primary success criterion: the engineer can understand what happened, why the conclusion is defensible, what uncertainty remains, and whether the confirmed mitigation improved the replayed incident.

The responder-facing noun is `incident`, not `replay`. `Deterministic incident replay` describes the controlled evaluation environment and appears as a compact environment badge or explanatory label. Scenario identifiers, seed keys, and replay implementation details never become the user's primary task language.

## 5. Secondary User Flow

```text
Choose one replay
        ↓
Choose baseline and candidate configurations
        ↓
Click Compare
        ↓
Run both real LLM configurations over identical replay/tool boundaries
        ↓
Display each actual RCA or abstention result
        ↓
Evaluate each completed trajectory
        ↓
Show RCA correctness separately
        ↓
Compare Grounding, Investigation Sufficiency, and Tool Efficiency
```

Secondary user: AI platform, evaluation, or agent reliability engineer.
Secondary success criterion: a team can detect a behavioral regression or improvement that final-answer accuracy alone would miss.

The demo may use one recorded pair when live nondeterminism does not naturally produce a useful contrast, but it must be labelled `Recorded comparison`. Never hard-code the live candidate to pass or the live baseline to fail.

## 6. MVP Scope

### Required

- Real OpenAI-backed adaptive investigation loop.
- Live, reconnectable investigation progress over application-owned events.
- Hypothesis-driven baseline and candidate prompt configurations.
- Five deterministic read tools over local replay data.
- Structured RCA-or-abstain result with evidence references.
- Incident-scoped follow-up chat that continues the same run.
- One confirmed simulated configuration rollback.
- Replay mutation and post-action verification.
- Deterministic RCA correctness plus three core Behavioral SLIs.
- Primary Investigator view and secondary Compare Agent Versions view.
- One main checkout scenario and one insufficient-evidence scenario. The existing payments scenario may remain if it stays coherent and cheap.
- Deterministic tests through an injected fake model provider.

### Explicitly out of scope

- Fine-tuning, model training, embeddings, vector databases, or RAG.
- Multi-agent orchestration.
- LLM-as-judge in the MVP.
- Live Grafana, Prometheus, Loki, Tempo, Kubernetes, Slack, PagerDuty, or cloud integrations.
- Real deployment, restart, scale, ticket, note, or notification actions.
- Production authentication, tenancy, RBAC, audit infrastructure, or background job systems.
- General-purpose remediation or an action framework.

## 7. Agent-Safe Data Boundary

Initial model and UI context may contain:

- incident ID and title;
- severity and start time;
- affected entry service;
- customer impact;
- high-level alert symptoms that do not reveal the cause.

The following are tool-retrieved only:

- service health;
- metrics and time series;
- matching logs;
- dependencies;
- recent changes.

The following are evaluator-only:

- expected RCA or expected abstention;
- required distinguishing evidence;
- causal concepts used for scoring;
- scenario-specific evaluation metadata.

Required seed cleanup:

- Scenario descriptions must be causal-neutral.
- Initial incident symptoms must not say that Postgres reached its limit, identify the bad configuration, state that evidence is inconclusive, or otherwise tell the agent what to conclude.
- Scenario API responses must not include `changes` or bulk `evidence` before the model retrieves them through tools.
- Frontend rails must not show recent changes before the corresponding tool call exists in the trace.

## 8. Investigator Runtime

The runtime is an application-owned loop around an injected model provider:

```text
incident-safe context + agent config + tool schemas
        ↓
model response
        ├─ function calls → execute deterministic read tools → append outputs → continue
        └─ structured final result → validate → persist trace → evaluate
```

Runtime requirements:

- Cap the loop at 8 successful read-tool calls and a bounded number of model turns.
- Validate tool names and arguments before execution.
- Return tool errors to the model as structured results without crashing the run.
- Reject unknown services and cross-scenario access.
- Persist actual tool order, arguments, returned evidence, duration, and status.
- Record model ID, agent configuration ID, prompt version/hash, tool-schema version, response IDs, latency, and token usage when available.
- Fail explicitly on malformed final output or budget exhaustion; do not synthesize a constant RCA as recovery.
- Keep provider code behind a small protocol so unit and API tests use deterministic fake response sequences and no network.

### Live investigation progress

Starting an investigation is asynchronous from the browser's perspective:

```text
POST /investigations
  → 202 Accepted with {run_id, scenario_id, status=queued|running}
  → application-owned worker executes the bounded investigator loop
  → each lifecycle/tool boundary appends a durable progress event
  → GET /investigations/{run_id}/events streams persisted and new events with SSE
  → completed event identifies the persisted InvestigationResponse
```

The MVP may use an in-process FastAPI worker because production background-job infrastructure is out of scope. The run and event records live in SQLite so the browser can reconnect without restarting the investigation. The event stream is read-only; only the explicit `POST /investigations` starts model work.

Required event types:

```text
investigation.started
hypotheses.updated
tool.started
tool.completed
investigation.completed
investigation.failed
```

Every event has a monotonically increasing event ID within the run, `run_id`, `created_at` timestamp, type, short user-facing summary, and a typed payload. Any exposed `scenario_id` is the neutral public ID, never an internal causal replay key. `tool.started` contains the tool name and concise purpose. `tool.completed` contains the bounded persisted `ToolCall`; the UI derives its compact summary from status, duration, and evidence count. The completed trace remains the canonical input to evaluation. Events never contain raw chain-of-thought, hidden model reasoning, provider secrets, evaluator truth, or unbounded raw telemetry.

The persisted status contract preserves the existing canonical completed response:

```text
GET /investigations/{run_id}
  → {
      run_id,
      scenario_id,
      status: queued | running | completed | failed,
      response: InvestigationResponse | null,
      error: string | null
    }
```

Only `completed` has a canonical response; only `failed` has a sanitized error. Chat and action endpoints return conflict until the run is complete. Comparisons remain synchronous in this take-home.

Event payloads are a discriminated union:

```text
investigation.started   {scenario_id, incident_id, agent_config_id}
hypotheses.updated      {hypotheses: HypothesisFinding[]}
tool.started            {sequence, tool_name, purpose}
tool.completed          {tool_call: ToolCall}
investigation.completed {tool_call_count}
investigation.failed    {error}
```

The full bounded `ToolCall` is present when a live step completes so the UI can immediately provide independently expandable arguments, structured result, and evidence. The default timeline row remains a compact summary.

### Agent configurations

`baseline` is a legitimate simple prompt:

> Investigate the incident with the available observability tools. Determine the most defensible root cause and recommend mitigation. If the evidence is insufficient, say so.

`candidate` is the primary, engineered policy:

- maintain two to four plausible hypotheses;
- choose evidence that discriminates between them;
- update hypothesis status after observations;
- ground causal claims in retrieved evidence;
- do not conclude until evidence is sufficient;
- abstain and identify missing evidence when necessary;
- propose mitigation and a verification plan.

The comparison must not encode expected pass/fail results. Both configurations are allowed to pass, fail, or differ across live runs.

## 9. Tool Contracts

All read tools return JSON-serializable data and stable evidence identifiers.

| Tool | Purpose | Does not establish by itself |
|---|---|---|
| `get_service_health(service)` | Summarize whether a service appears healthy, degraded, or critical | Root cause or configuration causality |
| `search_logs(service, query)` | Retrieve matching operational events | System-wide health or temporal causality |
| `get_metrics(service, metric_name)` | Inspect saturation, latency, error, and resource trends | Deployment/configuration history |
| `get_dependencies(service)` | Discover topology and plausible downstream alternatives | Which dependency caused the incident |
| `get_recent_changes(service)` | Retrieve deployments and configuration changes | That a temporally adjacent change is causal |

Each recorded tool call contains:

```text
sequence
tool_name
purpose                 # short model-visible decision summary
arguments
result
evidence_ids
status
duration_ms
```

Tool schemas must be meaningful enough for the model to choose correctly. Do not expose repository methods that return all evidence in bulk.

## 10. Structured Investigation Contract

The final investigation output should express:

```text
outcome: root_cause | abstain
root_cause: string | null
confidence: low | medium | high
evidence_ids: string[]
hypothesis_summary:
  - hypothesis
  - status: supported | weakened | unresolved
  - evidence_ids
mitigation
verification_plan: string[]
missing_evidence: string[]
action_proposal: ActionProposal | null
```

An abstention is valid behavior in an insufficient-evidence scenario. It is evaluated through RCA correctness, grounding, and sufficiency; it is not a fourth first-class Behavioral SLI.

## 11. Incident Chat

`POST /investigations/{run_id}/messages` continues the same investigation context. The runtime supplies the incident context, prior messages, trace, evidence already retrieved, and action/verification state. It does not expose evaluator truth.

Chat requirements:

- answer only from retrieved evidence and clearly identify uncertainty;
- allow evidence follow-ups such as “Why is payments not the cause?”;
- cite trace evidence identifiers in the structured response;
- never execute the rollback from natural-language chat alone;
- return an action proposal when the user requests the supported rollback.

## 12. Single Action and Verification

The only state-changing capability is:

```text
rollback_configuration(
  service="checkout",
  config_key="db.max_open_connections",
  from_value=80,
  to_value=20
)
```

Action lifecycle:

```text
agent proposes
  → API persists pending proposal
  → UI shows exact before/after values and expected impact
  → user confirms
  → backend validates proposal is still pending and allowed
  → replay state changes active → mitigated
  → deterministic tools return post-action telemetry
  → application code computes verified | not_verified from that telemetry
  → same investigator context assesses and explains the recovery evidence
  → action result becomes verified | not_verified
```

The application-owned verdict is authoritative; the LLM assessment may explain uncertainty but cannot override it. If the assessment fails after mutation, return the successful action and deterministic verdict with an explicit assessment error. Keep the original investigation trace and Behavioral Evaluation immutable; post-action calls belong to the action result. No confirmation means no mutation. Repeated confirmation must be idempotent. Remove restart, scale, deployment-version rollback, note, ticket, and generic action abstractions from the MVP.

## 13. Evaluation Contract

### Output metric — separate from the Behavioral SLO

**RCA correctness:** the result matches the evaluator-only expected cause, or appropriately abstains when the expected result is inconclusive.

### Core Behavioral SLIs

1. **Grounding:** causal claims and abstention explanations are supported by evidence IDs actually returned through the trace.
2. **Investigation Sufficiency:** the trace gathers enough independent and distinguishing evidence to support the conclusion or justify abstention.
3. **Tool Efficiency:** the trace stays within budget, avoids duplicate calls, uses known tools, and does not wander into irrelevant services.

```text
behavioral_slo_pass = grounded
                   && investigation_sufficient
                   && tool_efficient
```

An optional overall release decision may require both `rca_correct` and `behavioral_slo_pass`, but RCA correctness must remain visibly separate and must never be labelled a Behavioral SLI.

The evaluator only sees the completed trace plus evaluator-only scenario metadata. It cannot grant grounding credit for evidence present in SQLite but never retrieved by the agent.

## 14. API Contract

Read-only requests never start model work or mutate replay state.

| Method | Path | Behavior |
|---|---|---|
| `GET` | `/health` | Health and configured/live-model readiness |
| `GET` | `/scenarios` | Agent-safe scenario summaries |
| `GET` | `/scenarios/{scenario_id}` | Agent-safe incident context only |
| `POST` | `/investigations` | Explicitly start one live investigation |
| `GET` | `/investigations` | List persisted investigation-run summaries, newest first; read-only and never starts model work |
| `GET` | `/investigations/{run_id}` | Retrieve status and, when complete, the persisted run, trace, follow-up transcript, and confirmed action/verification state |
| `GET` | `/investigations/{run_id}/events` | Read-only SSE stream of persisted and new progress events |
| `POST` | `/investigations/{run_id}/messages` | Continue incident-scoped chat |
| `POST` | `/investigations/{run_id}/actions/{proposal_id}/confirm` | Confirm the one allowed rollback |
| `POST` | `/comparisons` | Explicitly start baseline and candidate runs |
| `GET` | `/comparisons` | List persisted comparison summaries, newest first; read-only and never starts model work |
| `GET` | `/comparisons/{comparison_id}` | Retrieve a persisted comparison |

Remove the side-effecting legacy `GET /comparisons/{scenario_id}`. Do not expose a bulk evidence endpoint to the primary UI.

`GET /investigations` returns strict summary objects with `run_id`, neutral public `scenario_id`, `incident_id`, `incident_title`, `status`, optional completed `outcome`, `created_at`, and `updated_at`. It lists responder-started Incident Investigator runs only; baseline and candidate arms owned by a persisted comparison are excluded because Compare Agent Versions is a separate feature. It does not return trace payloads, evaluator reasons, hidden replay keys, or answer-revealing evidence. The take-home may return the most recent 50 runs without pagination.

For a completed run, `GET /investigations/{run_id}` returns the canonical investigation response plus the persisted user/agent follow-up exchanges and the executed action result, including verification, when present. Reopening history is entirely read-only: it must reconstruct the honest completed workspace without issuing a chat, confirmation, model, or replay-mutating request. Unconfirmed proposals remain proposals; an already executed proposal must render as executed and must not reappear as a new confirmation request.

Scenario summary and detail responses include an agent-safe `target_sli` string sourced from incident metadata. It describes the operational objective only; it never contains the hidden cause, expected outcome, evaluator rule, or preselected evidence.

## 15. UI Contract

### Primary view — Incident Investigator

The default route is the operational workflow, not the comparison dashboard.

The approved desktop shell has three responsibilities but only one permanent primary canvas:

1. **Feature menu:** a compact hamburger menu in the header selects `Incident Investigator` or `Compare Agent Versions`. The current feature name remains visible in the header. Do not render permanent top-level route tabs.
2. **Shared left drawer:** `Investigations` and `Incident context` are mutually exclusive views in one drawer slot beside a slim control rail. Either view may be opened, and the drawer may be fully collapsed. Never render History and Context as two simultaneous full-width panels.
3. **Investigation workspace:** the remaining width is the primary conversation surface for selection readiness, live progress, evidence, RCA or abstention, confirmed action, recovery verification, and incident-scoped follow-up chat.

The `Investigations` drawer contains:

- a labelled `Find an incident` dropdown populated from `GET /scenarios` for this demo;
- recognizable persisted run titles from `GET /investigations`, grouped chronologically where useful;
- run status or outcome plus time as secondary text; and
- no answer-revealing evidence or evaluator truth.

History persists across ordinary `make run` restarts. `make seed` is the explicit reset path for a clean deterministic demo database; the launcher must initialize a missing database without unconditionally replacing an existing one.

Selecting an incident is read-only. It automatically switches the shared drawer to `Incident context`, loads only agent-safe source metadata, and renders a selected-but-not-started workspace with an explicit `Start investigation` button. The model call begins only from that button's `POST /investigations` action. If another run is active, incident selection is disabled or requires an explicit interruption confirmation; it never silently replaces the active run.

The `Incident context` drawer contains title, incident ID, severity, operational status, affected service, customer impact, target SLI, start time, and a compact `Replay environment · deterministic telemetry` label. It contains no second chat surface, comments feed, action controls, evaluation results, or pre-investigation tool evidence.

When a run begins, collapse the shared drawer to maximize workspace width while keeping the slim History and Context controls available. The live workspace shows application-owned progress, hypothesis updates, tool purposes/results, and retrieved evidence. The incident-scoped composer is disabled before a run exists and becomes available only after the investigation has enough same-run context for grounded follow-up.

After completion, organize the workspace around: RCA or abstention, supporting evidence, confirmation-required or completed rollback, recovery verification, a collapsed investigation trail, and a collapsed Behavioral SLO evaluation. Reopening `Incident context` must not replace or obscure the completed run state on desktop.

This take-home targets the desktop workflow. Do not add a dedicated mobile design or mobile-only feature behavior. The four-state selector used in design mockups (`Feature menu`, `Incident selected`, `Agent running`, `Completed`) is review chrome only and must never appear in the product.

Avoid splitting the primary experience into many equally weighted dashboards. The investigation timeline is the visual spine.

Use progressive disclosure rather than a raw tool-output wall:

- Keep the currently running step expanded.
- Render completed tool calls as compact summaries showing tool purpose, status, duration, and evidence count.
- Let users independently expand any completed step to inspect arguments, structured result, and evidence IDs; do not use a single-open accordion.
- Keep failures, RCA/abstention, confirmation-required action, and verification expanded.
- Show the first three evidence entries by default with `Show N more` for the remainder.
- After completion, collapse ordinary tool details while keeping the final result and Behavioral SLO summary prominent.
- Never display raw chain-of-thought. Hypothesis and purpose copy is concise application-visible state.

### Secondary view — Compare Agent Versions

- Use a compact, collapsible comparison-history drawer so completed comparisons can be reopened with `GET` only. History rows identify the incident and completion time without embedding full traces.
- Explicit `Compare` button.
- While the synchronous comparison request is pending, show an unmistakable application-owned in-progress state with elapsed time and both agent lanes. Do not fabricate tool events, per-agent phases, or streaming that the API does not expose.
- Actual baseline and candidate configuration metadata.
- Actual RCA/abstention outcome for each run.
- RCA correctness shown in a separate output section.
- Three Behavioral SLI rows plus Behavioral SLO composite.
- Side-by-side tool trajectories and evaluator reasons.
- No copy that assumes both RCAs pass or that either configuration must fail.
- Keep labels, headings, buttons, and explanatory copy compact. Comparison is a scorecard, not a second PRD page.

### Failure and fixture behavior

- No auto-fetch that invokes the LLM on mount.
- No silent `demoData` fallback after API or model failure.
- Display missing key, provider error, malformed output, and budget exhaustion states honestly.
- Recorded results are available only through a clearly labelled manual demo mode.

## 16. Ten-Minute Demo

```text
0:00–1:00  User problem and deterministic-replay/real-agent boundary
1:00–4:00  Start a live investigation and watch adaptive tool use
4:00–5:30  Inspect the evidence-backed RCA or abstention
5:30–6:30  Ask an incident-scoped follow-up question
6:30–7:30  Confirm the configuration rollback and verify recovery
7:30–9:00  Compare baseline and candidate with RCA separate from Behavioral SLOs
9:00–10:00 Architecture tradeoffs, testability, limitations, and next steps
```

The primary workflow must receive most of the demo time. The comparison is the Staff-level reveal, not the opening product.

## 17. Verification and Acceptance Gates

### Automated tests

- Model-provider unit tests use fake Responses API output/tool-call sequences and never use the network.
- Agent loop tests prove adaptive tool calls are executed and appended correctly.
- Ground-truth isolation tests prove expected outcomes never enter model context or tool output.
- Baseline/candidate tests prove configuration differences are prompts/policies, not hard-coded outcomes or trajectories.
- Evaluator tests keep RCA correctness separate and compute Behavioral SLO from only the three core SLIs.
- API tests prove all live work starts through `POST`; `GET` requests are read-only.
- Streaming tests prove accepted runs emit ordered lifecycle events, reconnect replays missed events without duplicating work, completion resolves to the canonical persisted trace, and failures terminate honestly.
- Chat tests prove the same `run_id` context continues without evaluator leakage.
- Action tests prove no mutation before confirmation, idempotent confirmation, allowed fixed target only, state mutation, and post-action verification.
- Frontend tests or contract checks prove no model call on mount and no silent fallback.
- One opt-in live smoke test may use `OPENAI_API_KEY`; it is excluded from the default suite.

### Final acceptance

1. A live real LLM autonomously investigates the checkout replay through deterministic tools.
2. The model is not given the answer, a complete evidence dump, or a predefined tool order.
3. The UI streams actual investigation progress and retrieved evidence, then shows structured decision summaries without raw chain-of-thought.
4. The investigator can abstain defensibly on insufficient evidence.
5. Follow-up chat continues the same run context.
6. Only the fixed configuration rollback exists, requires confirmation, mutates replay state, and is verified.
7. Comparison execution is explicit and uses two legitimate prompt configurations.
8. RCA correctness is displayed separately from Grounding, Sufficiency, Efficiency, and their composite.
9. API failure cannot masquerade as a successful live run.
10. `make test`, `make lint`, and `make build` pass.

## 18. Legacy Removal Map

Preserve the working replay, repository, observability-tool, FastAPI, Pydantic, evaluator, and UI foundations where they remain useful. Refactor the boundary; do not restart the repository wholesale.

| Area | Keep | Remove or rewrite |
|---|---|---|
| Investigator | Public runtime boundary and replay tools | RCA constants, scenario branches, deterministic tool sequences, mode-based shortcuts |
| Replay data | SQLite/SQLAlchemy and realistic evidence | causal scenario descriptions, answer-revealing initial symptoms, bulk pre-investigation evidence exposure |
| Evaluator | deterministic trace-only scoring and useful rule helpers | RCA correctness inside `behavioral_slo_pass`, assumptions that baseline passes/candidate fails |
| API | FastAPI and persisted runs | side-effecting comparison `GET`, missing chat/action contracts, implicit model execution |
| Frontend | component library, visual styling, topology/chart pieces that can consume real trace data | comparison-first home screen, auto comparison query, silent fixture fallback, hard-coded pass/fail and checkout RCA copy |
| Fixtures | deterministic fake-provider sequences and one labelled recorded demo | fixtures used as invisible production fallback |
| Tests | repository/evaluator/API foundations | tests asserting predefined tool paths or forced baseline/candidate verdicts |
| README/demo | repeatable commands and architecture explanation | “no API key required,” deterministic investigator, two-minute/five-minute flow, fixed comparison outcome |

## 19. Backend Directive — Codex SWE Agent

Ownership: `src/reliable_incident_agent/**`, `data/seeds/**`, `scripts/**`, backend tests, and backend dependency/configuration files. Do not edit `app/**` or this coordination document.

Mission: replace the legacy deterministic investigator boundary with the real provider-injected LLM runtime while preserving the useful replay and evaluator foundations.

Execution order:

1. Produce a short `KEEP / REWRITE / DELETE` inventory for the owned files and report contract concerns before editing.
2. Freeze Pydantic and OpenAPI contracts for investigation, chat, action, comparison, trace, and evaluation.
3. Add the OpenAI provider adapter and fake provider. No key in source, logs, fixtures, or commits.
4. Replace hard-coded RCA constants, scenario dispatch, and predetermined tool paths with the bounded function-calling loop.
5. Enforce agent-safe context and evaluator-only ground truth.
6. Implement prompt configurations with the same model/settings/tools and no encoded expected verdict.
7. Implement the single rollback state transition and post-action verification.
8. Change comparison creation to explicit `POST` and make all `GET`s read-only.
9. Correct Behavioral SLO composition to the three core SLIs, with RCA separate.
10. Replace legacy tests with fake-provider, safety, action, comparison, and leakage tests.
11. Run `make test` and `make lint`, then hand off the frozen OpenAPI shape and a concise change report to SWE2 and the architect.

Stop and escalate if a change would add a second action, expose evaluator truth, require an LLM judge, alter the primary product hierarchy, or force the frontend to guess an API contract.

## 20. Frontend Directive — Codex SWE Agent

Ownership: `app/**`, frontend tests, and frontend-specific build configuration. Do not edit `src/**`, seeds, backend tests, or this coordination document.

Mission: turn the current comparison-first command center into an investigator-first workflow that renders only real API state and then exposes the reliability comparison as a secondary view.

Execution order:

1. Produce a short `KEEP / REWRITE / DELETE` inventory for `app/**` before editing.
2. Remove the mount-time comparison request, silent demo fallback, flexible legacy response guessing, hard-coded RCA/pass/fail copy, and pre-investigation recent-change leakage.
3. Create the approved desktop shell: a hamburger feature menu for `Incident Investigator` and `Compare Agent Versions`, a slim drawer-control rail, one mutually exclusive `Investigations` / `Incident context` drawer, and the primary investigation workspace. Do not add the four-state mockup selector to the product.
4. Build the investigator timeline around SWE1's frozen contracts: asynchronous start, reconnectable live tool/evidence progress, hypothesis updates, final result, chat, action confirmation, and verification.
5. Make all model-backed operations explicit user actions with honest loading and failure states.
6. Implement the single rollback confirmation UI with exact before/after configuration values; never execute from chat text or proposal rendering.
7. Rebuild the comparison view so it renders actual outcomes and separates RCA correctness from the three Behavioral SLIs.
8. Apply progressive disclosure to the timeline: current step expanded, completed tool summaries compact, independently expandable evidence details, and RCA/abstention/action/verification prominent.
9. Retain charts/topology only when populated from retrieved trace evidence; delete checkout-specific decorative fixtures that can contradict the run.
10. If recorded-demo insurance remains, require an explicit `Recorded demo` control and persistent badge.
11. Run `make build` and any frontend checks, then hand off screenshots, tested flows, and contract mismatches to the architect.

The frontend agent may begin the legacy inventory and UI shell immediately. Integration against investigation/chat/action/comparison payloads begins only after the backend agent hands off the frozen API contract. Do not invent fields to work around a missing backend contract.

## 21. Coordination and Merge Protocol

1. Backend and frontend Codex agents work only in their assigned ownership areas.
2. Each starts with an inventory, then makes narrow, reviewable changes.
3. The backend agent freezes contracts before the frontend agent integrates them.
4. Both agents preserve unrelated user changes and avoid broad formatting churn.
5. Each handoff lists files changed, legacy removed, tests run, failures remaining, and architecture questions.
6. The architect reviews contract coherence, answer leakage, live/fallback honesty, action safety, evaluation semantics, and the ten-minute story before declaring the direction restored.

## 22. Current Baseline at Architecture Freeze

At the time this contract was written:

- Backend tests: `28 passed`.
- Python lint: passed.
- Frontend TypeScript/Vite build: passed with a non-blocking bundle-size warning.
- These checks validate the legacy implementation's internal consistency, not alignment with the new architecture.

Required commands:

```bash
make seed
make test
make lint
make build
```
