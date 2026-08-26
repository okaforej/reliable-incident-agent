# Reliable Incident Agent Coordination

## Goal

Build a polished local prototype for the Grafana AI/ML take-home:

> **Right answer, right reasons.**

The demo must show that final RCA accuracy is not enough. Two investigation trajectories can reach the same correct RCA, while only one gathered enough relevant evidence to be operationally reliable.

## Architecture

Use **Incident Replay** as the enterprise-grade abstraction:

```text
React Incident Command Center
  -> FastAPI
  -> run_investigation(...)
  -> observability tools
  -> Incident Replay repository
  -> SQLite replay store

InvestigationTrace
  -> evaluate_trace(...)
  -> BehavioralEvaluation
```

The implementation should stay local and deterministic, but use real open-source components rather than ad hoc files.

The architectural story is:

```text
Prototype:  Agent -> tools -> Incident Replay repository -> SQLite
Production: Agent -> tools -> Telemetry repository -> Grafana / Loki / Prometheus / Tempo
```

## Repository Shape

Build toward this structure:

```text
.
README.md
COORDINATION.md
requirements.txt
Makefile
.gitignore
package.json
vite.config.ts
tsconfig.json

data/
  seeds/
    checkout_db_pool_exhaustion.sql

var/
  replays.sqlite

src/
  reliable_incident_agent/
    __init__.py
    models.py
    db.py
    replay.py
    tools.py
    investigator.py
    evaluator.py

app/
  src/
    main.tsx
    App.tsx
    api/
    components/
    pages/
    styles/

scripts/
  run_demo.py

tests/
  test_evaluator.py
  test_runtime_evaluation.py
```

Use one Python package under `src/reliable_incident_agent/`. Do not create separate top-level packages like `agent/`, `tools/`, `shared/`, or `evaluation/`.

## Enterprise Open-Source Stack

Use these tools because they add real engineering surface without heavy infrastructure risk:

- **SQLite** for deterministic incident replay storage.
- **SQLAlchemy Core** for typed query boundaries over SQLite.
- **Pydantic** for `models.py` contracts and payload validation.
- **FastAPI** for the service boundary and OpenAPI docs.
- **React + Vite** for the enterprise demo UI.
- **shadcn/ui** for polished, accessible UI components.
- **TanStack Query** for typed server-state integration with FastAPI.
- **React Flow** for the service/dependency and investigation trajectory graph.
- **Recharts** or **Apache ECharts** for evidence charts.
- **pytest** or `unittest` for deterministic tests.
- **Makefile** for `make demo`, `make test`, and `make app`.
- **Ruff** for lint/format.

Optional:

- **Rich** for a clean CLI comparison table.
- **OpenTelemetry Python** for local trace spans around investigations and tool calls.
- **Grafana OSS** as a secondary evidence dashboard only, if already easy to provision.
- **Phoenix** or **Langfuse** only if we can wire traces quickly without making the demo depend on an external service.

Do not add Docker, live Grafana/Prometheus/Loki, or a remote tracing backend for the first working demo.

## UI Decision

Do not use Grafana as the primary product UI.

Use Grafana as inspiration and optional secondary evidence dashboard. The primary UI should be a custom **Incident Command Center** because this product needs workflow control, constrained chat, trajectory comparison, and evaluator explanation in one coherent experience.

Required UI regions:

- **Header:** product name, scenario selector, weak/reliable run controls, run status.
- **Left rail:** incident summary, timeline, affected services, recent changes.
- **Center:** constrained investigation chat/workflow. This is not a generic chatbot; it shows user prompt, agent reasoning summaries, tool-call cards, and final RCA.
- **Right rail:** behavioral SLO scorecard and evaluator reasons.
- **Bottom or secondary tab:** side-by-side weak vs reliable comparison.
- **Graph panel:** service topology and/or investigation trajectory using React Flow.
- **Evidence charts:** latency, error rate, DB connections, and change marker.

The core screen must answer in under 10 seconds:

1. What happened?
2. What did the agent inspect?
3. What RCA did it produce?
4. Was it right?
5. Was it right for the right reasons?

## Chat And Workflow

Build a constrained incident-investigation workflow, not an open-ended chatbot.

The chat surface should support:

- initial incident prompt;
- investigator messages;
- tool-call cards with arguments and structured results;
- final RCA message;
- evaluator summary message.

Do not support arbitrary production chat features such as memory, user accounts, attachments, Slack, or multi-incident conversations.

The main workflow:

```text
Select scenario
  -> Run weak investigation
  -> Run reliable investigation
  -> Compare trajectories
  -> Review behavioral SLOs
  -> Inspect evidence graph/charts
```

## Shared Models

`src/reliable_incident_agent/models.py` is the source of truth.

Keep the contract small:

```python
ToolCall:
    sequence: int
    tool_name: str
    arguments: dict
    result: dict

InvestigationTrace:
    incident_id: str
    incident_description: str
    tool_calls: list[ToolCall]
    final_root_cause: str

ExpectedOutcome:
    root_cause: str

BehavioralEvaluation:
    rca_correct: bool
    grounded: bool
    investigation_sufficient: bool
    tool_efficient: bool
    behavioral_slo_pass: bool
    reasons: list[str]
```

The investigator must not receive `ExpectedOutcome` or any hidden root-cause field. The evaluator may receive `ExpectedOutcome` only after the trace has been produced.

## Public APIs

Runtime:

```python
run_investigation(
    scenario_id: str,
    mode: Literal["weak", "reliable"],
) -> InvestigationTrace
```

Evaluation:

```python
evaluate_trace(
    trace: InvestigationTrace,
    expected: ExpectedOutcome,
) -> BehavioralEvaluation
```

The UI should call only these APIs.

FastAPI endpoints:

```text
GET  /scenarios
GET  /scenarios/{scenario_id}
POST /investigations
GET  /investigations/{run_id}
GET  /investigations/{run_id}/evaluation
GET  /comparisons/{scenario_id}
```

`POST /investigations` accepts:

```python
scenario_id: str
mode: Literal["weak", "reliable"]
```

The comparison endpoint returns both traces and both evaluations for the selected scenario.

## Data And Evaluation Rules

Evaluation must score only what the agent actually observed in `InvestigationTrace.tool_calls`.

The runtime may query SQLite through `replay.py` and tool interfaces. The evaluator must not query SQLite, seed SQL, hidden evidence, or scenario metadata to decide whether the agent was grounded. If the agent did not retrieve evidence through a tool call, the evaluator must treat that evidence as unobserved.

`ExpectedOutcome` may come from SQLite or seed data only after the trace has been produced, and only for RCA correctness.

## Required Demo Case

Implement one polished scenario first:

`checkout_db_pool_exhaustion`

The reliable path should gather enough evidence to connect:

- checkout latency/errors;
- checkout dependency on postgres;
- postgres connection saturation;
- recent checkout DB pool configuration change;
- final RCA.

The weak path should reach the same final RCA but with insufficient evidence.

Expected comparison:

```text
                 Weak Agent      Reliable Agent
RCA correct      PASS            PASS
Grounded         FAIL            PASS
Sufficient       FAIL            PASS
Efficient        PASS            PASS
Behavioral SLO   FAIL            PASS
```

## Behavioral SLIs

Use deterministic, explainable checks:

- **Grounded Investigation:** retrieved tool results visibly support the RCA.
- **Investigation Sufficiency:** evidence distinguishes the RCA from plausible alternatives.
- **Tool Efficiency:** no redundant, irrelevant, or excessive calls.

Do not require a golden tool sequence. Valid trajectories may differ.

## Tests

Tests must prove:

- weak trace: RCA correct, behavioral SLO fails;
- reliable trace: RCA correct, behavioral SLO passes;
- incorrect RCA is reported separately from behavior quality;
- evaluator scores observed tool results, not hidden fixture evidence.

## Waterfall Build Plan

Follow these phases in order. Do not begin a phase until the prior phase has its acceptance artifacts.

### Phase 1: Requirements Freeze

Artifacts:

- `COORDINATION.md` accepted as build spec.
- README outline with demo story and run commands.

Acceptance:

- One scenario only: `checkout_db_pool_exhaustion`.
- One primary UI: React Incident Command Center.
- One backend: FastAPI.
- One replay store: SQLite.

### Phase 2: Data And Contract Design

Artifacts:

- SQLite schema.
- Seed SQL for the scenario.
- Pydantic models.
- FastAPI endpoint schemas.

Acceptance:

- Database initializes from `make seed`.
- Models validate all API payloads.
- Investigator cannot access expected outcome.

### Phase 3: Backend Implementation

Artifacts:

- SQLAlchemy repository.
- Observability tools.
- `run_investigation`.
- `evaluate_trace`.
- FastAPI endpoints.

Acceptance:

- `make test` passes backend tests.
- Weak and reliable runs produce the same RCA.
- Weak fails behavioral SLO; reliable passes.

### Phase 4: Frontend Implementation

Artifacts:

- React command-center layout.
- Scenario selector.
- Run controls.
- Chat/tool timeline.
- Evidence charts.
- React Flow graph.
- SLO scorecard.
- Weak vs reliable comparison.

Acceptance:

- `make app` launches UI and API.
- Demo flow works without manual API calls.
- UI shows the thesis without narration.

### Phase 5: Hardening And Presentation

Artifacts:

- README final.
- screenshots or demo notes.
- CLI fallback with Rich if time permits.
- Ruff formatting.

Acceptance:

- Fresh clone can run in documented commands.
- Full demo completes in under five minutes.
- No real API keys or external services required.

## Scope Boundaries

Do not build:

- generic chatbot;
- full RCA platform;
- production Grafana integration;
- live telemetry stack;
- auth;
- Slack or ticketing integration;
- multiple scenarios before the first one is excellent.

Keep the demo reliable, readable, and runnable locally.
