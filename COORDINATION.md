# Reliable Incident Agent PRD

## 1. Product Summary

**Product name:** Reliable Incident Agent

**Tagline:** Right answer, right reasons.

Reliable Incident Agent is a local, enterprise-style prototype for evaluating incident-investigation agents. It demonstrates that final RCA correctness is not sufficient: an agent can reach the correct root cause through a weak investigation, while a reliable agent gathers evidence that supports and distinguishes the answer.

The prototype presents a complete incident replay workflow:

```text
Select incident replay
  -> run weak and reliable investigations
  -> inspect tool-call trajectories
  -> review RCA
  -> evaluate behavioral SLIs
  -> compare "correct answer, wrong reasons" against "correct answer, right reasons"
```

## 2. Product Goals

1. Show a compelling, staff-level systems idea in a five-minute demo.
2. Provide an enterprise-looking investigation console with clear workflow control.
3. Use deterministic local incident replay so multiple agent trajectories are evaluated against identical operational evidence.
4. Demonstrate trajectory-level behavioral evaluation over agent tool use.
5. Keep the implementation reliable, local, and runnable without external services.

## 3. Core Thesis

Traditional service reliability asks:

```text
Did the service meet its SLO?
```

Agentic incident response adds a second reliability question:

```text
Did the agent behave reliably while reaching its answer?
```

The demo must make this distinction visible:

```text
Weak trajectory:
  RCA correct
  Evidence insufficient
  Behavioral SLO FAIL

Reliable trajectory:
  RCA correct
  Evidence grounded and sufficient
  Behavioral SLO PASS
```

## 4. Target Audience

Primary audience:

- Grafana Labs AI/ML interviewers.

Secondary audience:

- Observability engineers evaluating agentic incident workflows.
- AI engineers discussing practical agent evaluation.

The demo should communicate senior/staff judgment: clean system boundaries, deterministic evaluation, operational relevance, and explicit limitations.

## 5. Selected Open-Source Stack

Use this stack for the implementation:

| Layer | Tool | Purpose |
|---|---|---|
| Replay storage | SQLite | Local deterministic incident replay database |
| Data access | SQLAlchemy Core | Query boundary between tools and replay DB |
| Contracts | Pydantic | Request, response, trace, and evaluation models |
| API | FastAPI | Local service boundary and OpenAPI documentation |
| Frontend | React + Vite | Primary incident command center UI |
| UI components | shadcn/ui | Accessible, polished enterprise components |
| Server state | TanStack Query | Fetching, caching, and API state in React |
| Graphs | React Flow | Service topology and investigation trajectory graph |
| Charts | Recharts | Incident metrics and evidence timelines |
| Tests | pytest | Deterministic behavior and integration tests |
| Dev workflow | Makefile | Repeatable local commands |
| Code quality | Ruff | Linting and formatting |

## 6. System Architecture

```text
React Incident Command Center
  -> FastAPI service
  -> investigator runtime
  -> observability tool interface
  -> SQLAlchemy replay repository
  -> SQLite replay database

InvestigationTrace
  -> behavioral evaluator
  -> BehavioralEvaluation
  -> API response
  -> UI scorecard and comparison
```

The key abstraction is the replay repository. The agent asks tools for logs, metrics, changes, and dependencies. Tools query SQLite through a repository boundary. The evaluator scores only the trace produced by those tool calls.

## 7. Repository Structure

Build this structure:

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
    api.py
    db.py
    evaluator.py
    investigator.py
    models.py
    replay.py
    tools.py

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
  test_api.py
  test_evaluator.py
  test_runtime_evaluation.py
```

## 8. Data Model

The first scenario is:

```text
checkout_db_pool_exhaustion
```

SQLite should contain enough operational evidence to support the demo:

| Table | Purpose |
|---|---|
| `scenarios` | Scenario metadata |
| `incidents` | Incident description, severity, time window, affected service |
| `services` | Service catalog |
| `dependencies` | Service-to-service and service-to-database topology |
| `metrics` | Time-series metric metadata |
| `metric_points` | Time-series values |
| `logs` | Structured log events |
| `changes` | Deployments/config changes during the incident window |
| `expected_outcomes` | Evaluation-only RCA target |
| `investigation_runs` | Persisted weak/reliable run metadata |
| `tool_calls` | Persisted observed tool-call results |
| `evaluations` | Persisted behavioral evaluation output |

The investigator runtime reads incident context and telemetry only through tool methods. Expected outcomes are loaded only after an investigation trace exists.

## 9. Shared Contracts

`src/reliable_incident_agent/models.py` owns the contracts.

Required Pydantic models:

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

InvestigationRequest:
    scenario_id: str
    mode: Literal["weak", "reliable"]

InvestigationResponse:
    run_id: str
    trace: InvestigationTrace
    evaluation: BehavioralEvaluation
```

## 10. API Requirements

FastAPI exposes these endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/scenarios` | List available replay scenarios |
| `GET` | `/scenarios/{scenario_id}` | Read scenario summary and incident context |
| `GET` | `/scenarios/{scenario_id}/evidence` | Read replay evidence for UI charts |
| `POST` | `/investigations` | Run one weak or reliable investigation |
| `GET` | `/investigations/{run_id}` | Read a persisted investigation trace |
| `GET` | `/investigations/{run_id}/evaluation` | Read persisted behavioral evaluation |
| `GET` | `/comparisons/{scenario_id}` | Return weak and reliable traces plus evaluations |

`POST /investigations` accepts:

```json
{
  "scenario_id": "checkout_db_pool_exhaustion",
  "mode": "reliable"
}
```

`GET /comparisons/{scenario_id}` is the main endpoint for the demo UI.

## 11. Observability Tools

The investigator can call these tools:

| Tool | Purpose |
|---|---|
| `get_service_health(service)` | Summarize status, latency, errors, and saturation for a service |
| `search_logs(service, query=None)` | Retrieve matching structured logs |
| `get_metrics(service, metric_name=None)` | Retrieve relevant time-series metrics |
| `get_recent_changes(service)` | Retrieve deployments/config changes in the incident window |
| `get_dependencies(service)` | Retrieve service dependencies and topology |

Tool results must be structured and include stable evidence IDs where available.

## 12. Investigation Modes

The prototype includes two deterministic modes for the same scenario.

### Weak Mode

Purpose: demonstrate a correct answer reached through insufficient investigation.

Expected behavior:

- performs one or two plausible but insufficient tool calls;
- returns the same correct RCA as reliable mode;
- lacks enough evidence to support and distinguish the RCA;
- fails groundedness and/or sufficiency.

### Reliable Mode

Purpose: demonstrate evidence-grounded investigation.

Expected behavior:

- inspects checkout health and symptoms;
- follows dependencies to postgres;
- retrieves postgres saturation evidence;
- retrieves checkout DB pool configuration change;
- distinguishes collateral payments symptoms from initiating failure;
- returns the same final RCA as weak mode;
- passes behavioral SLOs.

## 13. Behavioral Evaluation

The evaluator consumes:

```text
InvestigationTrace + ExpectedOutcome
```

The evaluator scores only observed tool-call results in `InvestigationTrace.tool_calls`.

Behavioral SLIs:

| SLI | Pass condition |
|---|---|
| RCA correctness | Final RCA matches expected root cause |
| Grounded investigation | Retrieved evidence visibly supports causal claims in the RCA |
| Investigation sufficiency | Retrieved evidence distinguishes the RCA from plausible alternatives |
| Tool efficiency | Tool calls are relevant, non-duplicative, and within budget |

Composite:

```python
behavioral_slo_pass = grounded and investigation_sufficient and tool_efficient
```

RCA correctness is reported separately from behavioral SLO pass/fail.

## 14. UI Requirements

The primary UI is a React Incident Command Center.

### Layout

Required regions:

| Region | Contents |
|---|---|
| Header | Product name, scenario selector, run actions, status |
| Incident rail | Summary, severity, time window, affected services, recent changes |
| Investigation console | Constrained chat/workflow transcript with tool-call cards |
| Evidence panel | Metric charts, log highlights, change marker |
| Graph panel | Service topology and/or investigation trajectory |
| SLO panel | RCA correctness, groundedness, sufficiency, efficiency, behavioral SLO |
| Comparison panel | Weak vs reliable trajectory comparison |

### Main User Flow

```text
Open app
  -> select checkout_db_pool_exhaustion
  -> run comparison
  -> review weak agent trajectory
  -> review reliable agent trajectory
  -> inspect evidence charts and topology
  -> present behavioral SLO result
```

### Chat/Workflow Surface

The transcript should include:

- incident prompt;
- investigator step summaries;
- tool-call cards with arguments and results;
- final RCA;
- evaluator summary.

The transcript is a workflow artifact, not an open-ended assistant chat.

### Visual Design

The UI should feel like an enterprise operations console:

- dense but readable layout;
- restrained color palette;
- compact cards and tables;
- clear status badges;
- small multiples for weak vs reliable comparison;
- charts that directly support the RCA.

The first screen should show the actual product workflow, not a marketing page.

## 15. Required Demo Output

The main comparison must show:

```text
                 Weak Agent      Reliable Agent
RCA correct      PASS            PASS
Grounded         FAIL            PASS
Sufficient       FAIL            PASS
Efficient        PASS            PASS
Behavioral SLO   FAIL            PASS
```

Both agents must produce the same final RCA:

```text
Checkout latency was caused by postgres connection exhaustion after checkout deployed a database pool max_open_connections change from 20 to 80.
```

## 16. Test Requirements

Required tests:

1. SQLite seed creates required tables and scenario data.
2. Pydantic models validate trace and evaluation payloads.
3. Weak investigation returns the expected RCA.
4. Reliable investigation returns the same expected RCA.
5. Weak investigation fails behavioral SLO.
6. Reliable investigation passes behavioral SLO.
7. Incorrect RCA fails correctness while behavior metrics remain independently reported.
8. Evaluator ignores hidden evidence that was not retrieved by tool calls.
9. FastAPI comparison endpoint returns both traces and evaluations.

## 17. Developer Commands

Makefile targets:

```text
make install
make seed
make api
make app
make demo
make test
make lint
```

Expected behavior:

- `make seed` creates `var/replays.sqlite`.
- `make api` starts FastAPI.
- `make app` starts the React UI.
- `make demo` runs the weak vs reliable comparison from CLI.
- `make test` runs backend and evaluator tests.

## 18. Waterfall Build Plan

### Phase 1: Requirements Freeze

Deliverables:

- PRD accepted as source of truth.
- README outline.
- dependency list finalized.

Acceptance:

- scenario, UI, API, and stack are fixed.

### Phase 2: Data And Contracts

Deliverables:

- SQLite schema and seed SQL.
- Pydantic models.
- repository interfaces.
- API schema definitions.

Acceptance:

- `make seed` creates valid replay DB.
- model validation tests pass.

### Phase 3: Backend

Deliverables:

- SQLAlchemy repository.
- observability tools.
- weak and reliable investigator modes.
- behavioral evaluator.
- FastAPI endpoints.

Acceptance:

- backend tests pass.
- comparison endpoint returns expected PASS/FAIL split.

### Phase 4: Frontend

Deliverables:

- React command center.
- API client.
- scenario selector.
- run comparison action.
- transcript/tool-call UI.
- evidence charts.
- topology/trajectory graph.
- behavioral SLO scorecard.

Acceptance:

- full demo works from the UI.
- user can explain the thesis from the first screen.

### Phase 5: Hardening

Deliverables:

- final README.
- screenshots or demo notes.
- lint/format pass.
- fresh-run verification.

Acceptance:

- full demo runs locally without external services.
- five-minute presentation path is documented.

## 19. Out Of Scope

The prototype does not include:

- production authentication;
- external integrations;
- live telemetry ingestion;
- multi-tenant data storage;
- deployment automation;
- multiple incident scenarios;
- model fine-tuning;
- general-purpose chat memory;
- production alerting or ticketing.

## 20. Final Acceptance Criteria

The project is complete when:

1. `make install`, `make seed`, `make test`, and the UI run commands work on a clean checkout.
2. The React UI displays the incident replay and comparison workflow.
3. The backend runs weak and reliable investigations against SQLite replay data.
4. Tool calls are captured in `InvestigationTrace`.
5. The evaluator consumes only observed trace evidence plus expected outcome.
6. The comparison shows correct RCA with failing behavior for weak mode.
7. The comparison shows correct RCA with passing behavior for reliable mode.
8. README explains the architecture, thesis, run commands, limitations, and next steps.
