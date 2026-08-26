# Reliable Incident Agent — Product and Architecture Contract

Status: source of truth. If implementation, tests, or documentation conflict
with this file, this file wins.

## 1. North Star

> **One real LLM autonomously investigates a deterministic incident replay using
> realistic observability tools.**

The deterministic replay is the controlled experiment; the LLM investigator is
the system under evaluation.

```text
DETERMINISTIC                    NON-DETERMINISTIC
Incident telemetry              Hypothesis formation
Observability tool results      Adaptive tool selection
Action state transition         Evidence interpretation
Expected outcome                RCA or abstention
Behavioral evaluator            Remediation proposal
```

## 2. Product Hierarchy

The product has two connected surfaces:

1. **Incident Investigator — primary.** An on-call engineer starts an
   investigation, watches evidence gathering, asks grounded follow-ups, confirms
   one safe simulated rollback, and verifies recovery.
2. **Compare Agent Versions — secondary.** An AI reliability engineer compares
   two legitimate prompt policies on independent copies of the same replay and
   evaluates their trajectories with Behavioral SLOs.

```text
Can AI investigate and help resolve this incident?
                         ↓
Can we measure whether that AI remains reliable as its configuration changes?
```

The responder-facing noun is **incident**. “Deterministic incident replay”
describes the controlled environment, not the user's task.

## 3. Non-Negotiable Guardrails

- The primary path uses a real OpenAI-backed LLM through the Responses API.
- The model chooses read tools and order within a fixed budget; no live
  trajectory or outcome is hard-coded.
- Initial model context is agent-safe. Expected outcomes and evaluator rules are
  loaded only after the trace completes.
- Baseline and candidate share the model, settings, replay, tools, and evidence.
  Their principal difference is investigation prompt policy.
- No raw chain-of-thought is requested, stored, or displayed.
- Only explicit POST actions start model work. GET and scenario selection are
  read-only.
- Failures are honest. No fixture or recorded result silently replaces a failed
  live request.
- The only state-changing capability is the confirmed checkout database-pool
  rollback defined below.
- Every run and comparison arm receives an isolated replay instance.
- RCA correctness remains separate from the three Behavioral SLO dimensions.

## 4. Primary User Flow

```text
Select incident → review safe context → start investigation
  → stream hypotheses, tools, and evidence → RCA or abstention
  → grounded follow-up → propose rollback → human confirmation
  → mutate isolated replay → verify telemetry → explain recovery
```

The engineer must be able to understand what happened, why the conclusion is
defensible, what uncertainty remains, and whether mitigation helped.

## 5. Secondary User Flow

```text
Choose incident → run baseline and candidate on independent replay instances
  → display actual RCA or abstention → compare trajectories
  → show RCA correctness separately from Behavioral SLOs
```

Neither configuration is required to win. A manually selected recorded
comparison may provide demo insurance only when it is persistently labelled.

## 6. System Design

```text
React workspace
    │ explicit POST / read-only GET / SSE
FastAPI
    ├── application-owned investigation worker
    ├── provider-injected LLM tool loop
    ├── deterministic observability tools
    ├── deterministic evaluator
    └── SQLAlchemy repository
            └── SQLite replay, runs, events, chat, actions, comparisons
```

The provider stays behind a small protocol. Offline tests inject deterministic
model responses and never require credentials or network access.

## 7. Data Boundary

Initial model and UI context may contain incident ID, title, severity, start time,
affected entry service, customer impact, and causal-neutral alert symptoms.

The model must retrieve service health, metrics, logs, dependencies, and recent
changes through tools. Expected RCA or abstention, distinguishing evidence, causal
concepts, and scoring metadata are evaluator-only.

Public scenarios remain neutral:

- `checkout_latency_spike`
- `payment_submission_failures`
- `frontend_error_spike`

Public responses never expose causal replay keys, bulk evidence, or answer-revealing
changes before tool retrieval.

## 8. Investigator Runtime

```text
safe context + prompt policy + tool schemas
        ↓
model response
  ├── function calls → validate → execute tools → append outputs → continue
  └── structured result → validate → persist trace → evaluate
```

Runtime requirements:

- Maximum eight successful read-tool calls and bounded model turns.
- Validate tool names and arguments; reject unknown services and cross-scenario
  access.
- Return structured tool errors to the model without crashing the run.
- Persist actual tool order, arguments, results, evidence IDs, duration, and
  status.
- Record model/configuration IDs, prompt and tool-schema versions, response IDs,
  latency, and token usage when available.
- Malformed output and budget exhaustion fail explicitly.

The five read tools are:

| Tool | Purpose |
|---|---|
| `get_service_health` | Summarize service state |
| `search_logs` | Retrieve matching operational events |
| `get_metrics` | Inspect saturation, latency, errors, and resources |
| `get_dependencies` | Discover topology and plausible alternatives |
| `get_recent_changes` | Retrieve deployments and configuration changes |

Each result exposes stable evidence IDs. No tool returns all evidence in bulk.

The structured final result includes outcome, root cause, confidence, evidence
IDs, hypothesis statuses, mitigation, verification plan, missing evidence, and an
optional action proposal. Abstention is valid behavior when evidence is
insufficient.

## 9. Durable Progress and History

Starting an investigation is asynchronous:

```text
POST /investigations → 202 {run_id, scenario_id, status}
GET /investigations/{run_id}/events → persisted and live SSE events
GET /investigations/{run_id} → canonical status and completed response
```

Required event types are `investigation.started`, `hypotheses.updated`,
`tool.started`, `tool.completed`, `investigation.completed`, and
`investigation.failed`.

Events have monotonically increasing IDs and bounded typed payloads. They may
contain concise hypotheses, tool purposes, `ToolCall` results, and evidence, but
never hidden reasoning, credentials, evaluator truth, or unbounded telemetry.

Runs and events persist in SQLite so the UI can reconnect without repeating model
work. `GET /investigations` and `GET /comparisons` return compact newest-first
history. Reopening history is entirely read-only and restores persisted chat and
action state. `make run` preserves history; `make seed` explicitly resets it.

Comparison execution remains synchronous for this take-home. Its waiting UI shows
honest elapsed progress and both agent lanes without inventing tool events.

## 10. Follow-Up and Action Safety

Follow-up chat continues the same run with its incident context, prior messages,
retrieved evidence, trace, and action state. It never receives evaluator truth and
cannot execute an action from natural-language text.

The only state-changing operation is:

```text
rollback_configuration(
  service="checkout",
  config_key="db.max_open_connections",
  from_value=80,
  to_value=20
)
```

The agent proposes; the UI displays exact values; the user confirms; the backend
validates the pending proposal and mutates only that run's replay. Application
code then computes `verified | not_verified` from post-action telemetry. The LLM
may explain that evidence but cannot override the deterministic verdict.

No confirmation means no mutation. Repeated confirmation is idempotent. The
original investigation trace and evaluation remain immutable. If recovery
assessment fails after mutation, the completed action and deterministic verdict
remain available with an explicit assessment error.

## 11. Evaluation Contract

**RCA correctness** is an output metric: the result matches the evaluator-only
expected cause or appropriately abstains when the expected result is inconclusive.

The Behavioral SLO contains exactly three dimensions:

1. **Grounding** — causal claims or abstention explanations cite evidence actually
   retrieved in the trace.
2. **Investigation Sufficiency** — the trace gathers independent, distinguishing
   evidence for its conclusion or abstention.
3. **Tool Efficiency** — the trace stays within budget and avoids duplication,
   unknown tools, and irrelevant wandering.

```text
behavioral_slo_pass = grounded
                   && investigation_sufficient
                   && tool_efficient
```

The evaluator sees only the completed trace and evaluator-only expected metadata.
It cannot credit hidden SQLite evidence that the agent did not retrieve.

## 12. API Surface

| Method | Path | Behavior |
|---|---|---|
| `GET` | `/health` | API and provider readiness |
| `GET` | `/scenarios[/{id}]` | Agent-safe incident summaries or context |
| `POST` | `/investigations` | Start one live investigation |
| `GET` | `/investigations` | Read investigation history |
| `GET` | `/investigations/{run_id}` | Read status and canonical persisted state |
| `GET` | `/investigations/{run_id}/events` | Reconnectable progress stream |
| `POST` | `/investigations/{run_id}/messages` | Continue run-scoped chat |
| `POST` | `/investigations/{run_id}/actions/{proposal_id}/confirm` | Confirm the fixed rollback |
| `POST` | `/comparisons` | Run baseline and candidate |
| `GET` | `/comparisons[/{id}]` | Read comparison history or result |

Chat and action endpoints return conflict until the run completes. Only completed
runs have canonical responses; failed runs contain sanitized user-facing errors.

## 13. UI Contract

The desktop application opens on **Incident Investigator**. A compact hamburger
menu switches between it and **Compare Agent Versions**.

The investigator uses one collapsible left drawer with mutually exclusive
**History** and **Incident context** views, plus a primary timeline/chat workspace.
Selecting an incident is read-only. Starting a run collapses the drawer and
streams actual progress. Completed tool calls become compact, independently
expandable rows; RCA/abstention, action confirmation, verification, and Behavioral
SLO summary remain prominent. Never display raw chain-of-thought.

The comparison view uses compact setup and history, an explicit **Compare** action,
an unmistakable honest pending state, actual outcomes, RCA correctness in its own
section, the three Behavioral SLI rows, the composite, and both tool trajectories.
Copy must not assume either configuration passes or fails.

Missing credentials, provider errors, malformed output, and budget exhaustion are
shown honestly. No model request runs on mount and no fixture fallback is silent.
This take-home targets desktop; dedicated mobile behavior is out of scope.

## 14. Scope

Required scenarios include the checkout incident and an insufficient-evidence
case. A coherent payments scenario may remain.

Explicitly out of scope:

- fine-tuning, embeddings, vector databases, RAG, multi-agent orchestration, or
  LLM-as-judge;
- live Grafana, Prometheus, Loki, Tempo, Kubernetes, cloud, ticketing, or chat
  integrations;
- production authentication, tenancy, RBAC, background jobs, and generalized
  remediation;
- any state-changing action beyond the confirmed fixed rollback.

## 15. Acceptance Gates

The default suite proves provider injection, adaptive tool execution, ground-truth
isolation, strict schemas, read-only GETs, ordered SSE/reconnect, history restore,
same-run chat, action confirmation/idempotency, evaluation semantics, provider
failure handling, and absence of silent frontend fallback.

Required commands:

```bash
make seed
make test
make lint
make build
git diff --check
```

Live smoke testing is explicit and requires both `OPENAI_API_KEY` and
`OPENAI_MODEL`; it is excluded from the default suite.
