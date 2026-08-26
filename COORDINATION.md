# Reliable Incident Agent PRD

## 1. Product Summary

**Product name:** Reliable Incident Agent

**Primary product surface:** AI Incident Investigator

**Secondary product surface:** Reliability / Compare Agent Versions

**Tagline:** Investigate, act, verify, and measure whether the agent remains reliable.

Reliable Incident Agent is a local, enterprise-style prototype for AI-assisted incident response. The primary product is an incident-scoped AI investigator for on-call engineers. It receives incident context, forms hypotheses, chooses observability tools, gathers evidence, produces a defensible RCA or abstains when evidence is insufficient, proposes mitigation, supports interactive follow-up, executes simulated remediation actions with human confirmation, and verifies the outcome.

The Staff-level reliability layer wraps that investigator with deterministic Incident Replay and Behavioral SLO evaluation. It shows how teams can compare baseline and candidate agent configurations and detect regressions that final RCA accuracy alone would miss.

The product answers two nested questions:

```text
1. Can AI meaningfully help investigate and resolve incidents?
2. How do we know the AI investigator itself is behaving reliably as it changes?
```

## 2. Product Goals

1. Demonstrate an AI incident investigator that maps to Grafana's operational loop: detect, triage, investigate, resolve, and verify.
2. Make the primary experience useful to an on-call engineer, not only to an evaluation engineer.
3. Support incident-scoped chat as a continuation of the investigation, not as a generic chatbot.
4. Demonstrate safe agentic action through simulated replay actions with explicit human confirmation.
5. Provide a secondary reliability workflow that compares baseline and candidate configurations using Behavioral SLOs.
6. Use deterministic local replay data so investigations, actions, and evaluations are repeatable and reviewable.
7. Include multiple incident scenarios so the prototype does not look engineered around one answer.
8. Keep the implementation local, enterprise-looking, and runnable without real infrastructure.

## 3. Core Thesis

Modern incident response needs AI that can do more than summarize dashboards. The product thesis is:

```text
Incident fires
  -> AI investigates with observability tools
  -> AI explains evidence and uncertainty
  -> AI proposes or performs confirmed sandbox actions
  -> AI verifies recovery
```

As incident agents become operational software, teams also need reliability engineering for the agent itself:

```text
Agent change
  -> Incident Replay suite
  -> RCA + trajectory
  -> Behavioral SLIs / SLOs
  -> release decision
```

The demo should first prove:

```text
The AI can investigate an incident and guide resolution.
```

Then reveal:

```text
Two agent configurations can produce the same correct RCA while one regresses behaviorally.
```

## 4. User Stories

### Primary User: On-Call / Operations Engineer

As an on-call engineer, I want an AI investigator to autonomously investigate an incident using available observability evidence, test plausible causes, and give me a defensible root cause and resolution path, or tell me when the evidence is insufficient, so I can resolve incidents faster without blindly trusting an AI-generated answer.

### Primary User Flow

```text
Incident fires / user selects replay
        ↓
AI receives incident context
        ↓
Forms plausible hypotheses
        ↓
Chooses observability tools
        ↓
Metrics / logs / changes / dependencies
        ↓
Interprets evidence
        ↓
Adaptively investigates further
        ↓
Decision
  ├─ sufficient evidence -> RCA -> mitigation -> verification
  └─ insufficient evidence -> abstain -> missing evidence
        ↓
Incident-scoped chat follow-up
        ↓
Optional confirmed sandbox action
        ↓
Post-action verification
```

### Secondary User: Agent Reliability Engineer

As the engineer responsible for the incident agent, I want to replay representative incidents against baseline and candidate configurations and measure behavioral reliability, so that prompt, model, tool, or workflow changes do not introduce regressions that final-answer accuracy misses.

### Secondary User Flow

```text
Baseline configuration ─┐
                        ├─ same Incident Replay
Candidate configuration ┘
                              ↓
                       investigations
                              ↓
                      compare RCA accuracy
                              ↓
                       both may be correct
                              ↓
                      Behavioral SLOs
                              ↓
                  did behavior regress?
                              ↓
                       inspect trajectory
```

## 5. Product Hierarchy

The UI and demo must preserve this hierarchy:

```text
AI INCIDENT INVESTIGATOR
          │
          ├─ Autonomous Investigation
          │    ├─ forms hypotheses
          │    ├─ selects tools
          │    ├─ gathers evidence
          │    ├─ produces RCA or abstains
          │    ├─ proposes mitigation
          │    └─ verifies recovery
          │
          └─ Interactive Agent
               ├─ user asks follow-ups
               ├─ asks for evidence
               ├─ requests actions
               ├─ agent invokes tools
               └─ verifies results

RELIABILITY LAYER
          │
          └─ Replay / Compare Versions
               ├─ same incident and evidence
               ├─ baseline vs candidate trajectories
               ├─ RCA parity
               └─ Behavioral SLO reveal
```

Behavioral SLOs are not the primary product. They are the reliability mechanism around the primary AI investigator.

## 6. Target Audience

Primary audience:

- Grafana Labs AI/ML interviewers evaluating whether the prototype maps to operational incident workflows.

Primary product user:

- On-call engineers, SREs, and operations engineers investigating incidents.

Secondary product user:

- AI/platform engineers maintaining and releasing incident-agent configurations.

The demo should communicate senior/staff judgment: operational relevance, safe autonomy boundaries, deterministic evaluation, clean system boundaries, and explicit limitations.

## 7. Selected Open-Source Stack

Use this stack for the implementation:

| Layer | Tool | Purpose |
|---|---|---|
| Replay storage | SQLite | Local deterministic incident replay database |
| Data access | SQLAlchemy Core | Query boundary between tools and replay DB |
| Contracts | Pydantic | Request, response, trace, chat, action, and evaluation models |
| API | FastAPI | Local service boundary and OpenAPI documentation |
| Frontend | React + Vite | Primary AI Incident Investigator UI |
| UI components | shadcn/ui style | Accessible, polished enterprise components |
| Server state | TanStack Query | Fetching, caching, and API state in React |
| Graphs | React Flow | Service topology and investigation trajectory graph |
| Charts | Recharts | Incident metrics and evidence timelines |
| Tests | pytest | Deterministic behavior, actions, and API tests |
| Dev workflow | Makefile | Repeatable local commands |
| Code quality | Ruff | Linting and formatting |

No real infrastructure integration is required. If an LLM-backed investigator mode is added, it may use the provided OpenAI API key for reasoning, but all tools and action effects remain constrained to the local Incident Replay sandbox.

## 8. System Architecture

```text
React AI Incident Investigator
  -> FastAPI service
  -> investigator runtime
  -> incident-scoped chat/action runtime
  -> observability and action tool interfaces
  -> SQLAlchemy replay repository
  -> SQLite replay database

InvestigationTrace
  -> Behavioral evaluator
  -> BehavioralEvaluation
  -> Reliability / Compare Versions UI
```

The replay repository is the key boundary. Read tools query logs, metrics, changes, dependencies, deployment state, and service health through the repository. Action tools mutate only replay sandbox state. The evaluator scores only the observed trajectory, not hidden replay evidence.

## 9. Repository Structure

Build and maintain this structure:

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

## 10. Replay Data Model

The replay database contains at least three scenarios:

| Scenario | Purpose |
|---|---|
| `checkout_db_pool_exhaustion` | Correlates checkout latency, postgres saturation, dependency topology, and a recent DB pool config change |
| `payments_gateway_timeout` | Requires following checkout symptoms to a downstream payments dependency and gateway timeout change |
| `insufficient_frontend_evidence` | Tests that the agent avoids overclaiming when available evidence is inconclusive |

SQLite should contain enough operational evidence to support investigation, chat follow-up, simulated actions, and verification:

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
| `investigation_runs` | Persisted investigation metadata |
| `tool_calls` | Persisted observed tool-call results |
| `evaluations` | Persisted behavioral evaluation output |
| `replay_actions` | Simulated action proposals and confirmed executions |
| `replay_state` | Sandbox state before and after confirmed actions |

Expected outcomes are loaded only after an investigation trace exists.

## 11. Shared Contracts

`src/reliable_incident_agent/models.py` owns the contracts.

Required model families:

```python
ToolCall:
    sequence: int
    tool_name: str
    arguments: dict
    result: dict

InvestigationTrace:
    incident_id: str
    incident_description: str
    hypotheses: list[str]
    tool_calls: list[ToolCall]
    final_root_cause: str
    mitigation: str | None
    verification_plan: list[str]

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
    mode: Literal["baseline", "candidate"]

InvestigationResponse:
    run_id: str
    trace: InvestigationTrace
    evaluation: BehavioralEvaluation | None

ChatTurn:
    role: Literal["user", "agent", "tool"]
    content: str
    tool_calls: list[ToolCall]
    action_proposal: ActionProposal | None

ActionProposal:
    id: str
    action_name: str
    arguments: dict
    expected_impact: str
    requires_confirmation: bool
    status: Literal["proposed", "confirmed", "executed", "rejected"]

ActionResult:
    proposal_id: str
    action_name: str
    result: dict
    verification_tool_calls: list[ToolCall]
```

Implementation may keep fields minimal, but the product contract must support investigation history, chat continuation, action proposal, confirmation, execution, and verification.

## 12. API Requirements

FastAPI exposes these endpoint groups:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/scenarios` | List available replay scenarios |
| `GET` | `/scenarios/{scenario_id}` | Read scenario summary and incident context |
| `GET` | `/scenarios/{scenario_id}/evidence` | Read replay evidence for UI charts |
| `POST` | `/investigations` | Run one investigator configuration |
| `GET` | `/investigations/{run_id}` | Read a persisted investigation trace |
| `POST` | `/investigations/{run_id}/chat` | Continue the incident-scoped agent conversation |
| `POST` | `/actions/{proposal_id}/confirm` | Confirm and execute a proposed replay action |
| `GET` | `/investigations/{run_id}/evaluation` | Read persisted behavioral evaluation |
| `GET` | `/comparisons/{scenario_id}` | Return baseline and candidate traces plus evaluations |

`POST /investigations` accepts:

```json
{
  "scenario_id": "checkout_db_pool_exhaustion",
  "mode": "baseline"
}
```

`POST /investigations/{run_id}/chat` accepts:

```json
{
  "message": "Show me the evidence that rules out payments."
}
```

`POST /actions/{proposal_id}/confirm` executes only sandboxed replay actions. It must not connect to production infrastructure.

## 13. Tool Model

### Read Tools

The investigator and chat continuation can call these tools autonomously:

| Tool | Purpose |
|---|---|
| `get_service_health(service)` | Summarize status, latency, errors, and saturation for a service |
| `search_logs(service, query=None)` | Retrieve matching structured logs |
| `get_metrics(service, metric_name=None)` | Retrieve relevant time-series metrics |
| `get_recent_changes(service)` | Retrieve deployments/config changes in the incident window |
| `get_dependencies(service)` | Retrieve service dependencies and topology |
| `get_deployment(service)` | Retrieve active and previous deployment/config versions |

Tool results must be structured and include stable evidence IDs where available.

### Action Tools

Action tools operate only against the deterministic Incident Replay sandbox:

| Tool | Purpose |
|---|---|
| `rollback_deployment(service, target_version)` | Simulate rollback to a prior deployment/config |
| `restart_service(service)` | Simulate restart impact |
| `scale_service(service, replicas)` | Simulate capacity change |
| `create_incident_note(content)` | Persist a replay-local incident note |

State-changing action tools must not execute silently. The agent proposes the action, explains expected impact, waits for explicit confirmation, executes the sandbox action, then verifies outcome with read tools.

Required action pattern:

```text
User requests action
  -> agent proposes action and expected impact
  -> UI shows confirmation control
  -> user confirms
  -> action tool mutates replay state
  -> agent queries telemetry again
  -> agent reports verification result
```

## 14. Investigator Runtime Requirements

The investigator must support two connected modes of use:

### Autonomous Investigation

Expected behavior:

- receives incident context;
- forms plausible hypotheses;
- chooses read tools based on those hypotheses;
- gathers logs, metrics, dependencies, changes, and deployment state;
- interprets evidence in readable step summaries;
- returns RCA and mitigation when evidence is sufficient;
- returns an inconclusive/insufficient-evidence answer when evidence is not sufficient;
- includes a verification plan.

### Interactive Agent Continuation

Chat is a continuation of the active investigation. It must have access to the same incident context, retrieved evidence, tool-call history, action history, and replay tools.

Valid follow-up examples:

- "What evidence supports this RCA?"
- "What evidence rules out payments?"
- "Check whether another service has the same symptom."
- "What should I do first?"
- "Rollback the problematic deployment."
- "Verify whether the mitigation worked."

The agent should decide whether to answer from existing context or invoke another read tool. For action requests, it must propose the action and require confirmation before execution.

## 15. Investigation Configurations

The prototype includes deterministic investigator configurations for repeatable demonstration.

### Baseline Configuration

Purpose: represent the accepted investigator behavior.

Expected behavior for `checkout_db_pool_exhaustion`:

- inspects checkout health and symptoms;
- forms multiple plausible hypotheses;
- follows dependencies to postgres and payments;
- retrieves postgres saturation evidence;
- retrieves checkout DB pool configuration change;
- distinguishes collateral payments symptoms from initiating failure;
- returns the correct final RCA;
- proposes rollback of the problematic configuration;
- verifies recovery after confirmed sandbox rollback;
- passes behavioral SLOs.

### Candidate Configuration

Purpose: represent a plausible model/prompt/tool configuration change that preserves output accuracy but regresses investigation behavior.

Expected behavior:

- performs a plausible shortcut investigation;
- returns the same correct RCA as baseline for the main scenario;
- lacks enough evidence to support and distinguish the RCA;
- may still propose a plausible mitigation;
- fails groundedness and/or sufficiency.

For `payments_gateway_timeout`, the investigator should follow checkout symptoms to payments, retrieve payments logs/metrics/changes, and avoid blaming postgres.

For `insufficient_frontend_evidence`, the investigator should gather available frontend evidence and return an inconclusive RCA instead of fabricating a precise root cause.

## 16. Behavioral Evaluation

The evaluator consumes:

```text
InvestigationTrace + ExpectedOutcome
```

The evaluator scores only observed tool-call results in `InvestigationTrace.tool_calls`.

Behavioral SLIs:

| SLI | Pass condition |
|---|---|
| RCA correctness | Final RCA matches expected root cause, or the expected inconclusive outcome when evidence is insufficient |
| Grounded investigation | Retrieved evidence visibly supports causal claims in the RCA or abstention |
| Investigation sufficiency | Retrieved evidence distinguishes the RCA from plausible alternatives or justifies abstention |
| Tool efficiency | Tool calls are relevant, non-duplicative, and within budget |

Composite:

```python
behavioral_slo_pass = rca_correct and grounded and investigation_sufficient and tool_efficient
```

RCA correctness should still be displayed separately so the demo can show output-layer parity before revealing behavioral reliability.

## 17. UI Requirements

The primary UI is an AI Incident Investigator workspace.

### Required Top-Level Views

| View | Purpose |
|---|---|
| Investigator | Primary incident investigation, chat, action, mitigation, and verification workflow |
| Reliability / Compare Versions | Secondary baseline-vs-candidate replay and Behavioral SLO workflow |

### Investigator View Layout

| Region | Contents |
|---|---|
| Header | Product name, scenario selector, run investigation action, status |
| Incident rail | Summary, severity, time window, affected services, recent changes |
| Hypothesis panel | Active hypotheses and evidence status |
| Investigation timeline | Tool-call cards, evidence summaries, reasoning steps |
| Evidence panel | Metric charts, log highlights, change marker |
| Graph panel | Service topology and investigation trajectory |
| RCA / abstention panel | Root cause, confidence, missing evidence when inconclusive |
| Mitigation panel | Recommended action, expected impact, verification plan |
| Chat/action panel | Incident-scoped follow-up questions, tool use, action proposals, confirmations, verification |

### Reliability View Layout

| Region | Contents |
|---|---|
| Output-only panel | Baseline RCA PASS, candidate RCA PASS, identical/different RCA |
| SLO reveal panel | Groundedness, sufficiency, efficiency, composite Behavioral SLO |
| Trajectory comparison | Baseline vs candidate tool calls and evidence coverage |
| Scenario switcher | Additional scenarios proving the system is not hard-coded to one incident |

### Chat/Action Surface Requirements

Chat must not be a generic assistant. It is incident-scoped and must:

- reference the active incident;
- use existing investigation history;
- invoke read tools when a follow-up needs more evidence;
- propose action tools when the user asks for remediation;
- require explicit confirmation before state-changing tools;
- show action results and verification evidence;
- avoid claiming production impact because all actions are replay-local.

## 18. Required Demo Output

### Primary Demo: AI Incident Investigator

The main demo should show:

```text
Incident selected
  -> hypotheses generated
  -> read tools invoked
  -> evidence interpreted
  -> RCA or abstention produced
  -> mitigation proposed
  -> user asks follow-up
  -> agent answers with evidence or invokes another read tool
  -> user requests rollback
  -> agent proposes action
  -> user confirms
  -> replay action executes
  -> agent verifies recovery
```

Example action flow:

```text
User: Roll back checkout to the previous configuration.

Agent:
I can roll back checkout-v42 to checkout-v41.

Expected impact:
Restore the previous DB pool configuration and reduce postgres connection saturation.

[Confirm rollback]

rollback_deployment("checkout", "v41")

Verification:
- postgres connection saturation cleared
- checkout p99 recovered
- timeout rate returned to baseline
```

### Secondary Demo: Reliability Layer

The reliability demo should show:

```text
Baseline RCA:  PASS
Candidate RCA: PASS

Output-only evaluation says: equivalent.

Behavioral SLO reveal:
                 Baseline        Candidate
RCA accuracy     PASS            PASS
Grounded         PASS            FAIL
Sufficient       PASS            FAIL
Efficient        PASS            PASS
Behavioral SLO   PASS            FAIL
```

Both configurations may produce the same final RCA:

```text
Checkout latency was caused by postgres connection exhaustion after checkout deployed a database pool max_open_connections change from 20 to 80.
```

The intended reaction is:

```text
The final answer did not reveal that the investigation behavior regressed.
```

## 19. Test Requirements

Required tests:

1. SQLite seed creates required tables and scenario data.
2. Pydantic models validate trace, chat, action, and evaluation payloads.
3. Autonomous investigation returns hypotheses, tool calls, RCA/abstention, mitigation, and verification plan.
4. Read tools can be invoked from both autonomous investigation and incident-scoped chat.
5. Action tools create proposals and do not execute before confirmation.
6. Confirmed action tools mutate only replay sandbox state.
7. Post-action verification queries replay telemetry and reports recovery or remaining risk.
8. Baseline investigation returns the expected RCA for the main scenario.
9. Candidate investigation returns the same expected RCA for the main scenario.
10. Baseline investigation passes behavioral SLO.
11. Candidate investigation fails behavioral SLO.
12. Incorrect RCA fails RCA correctness and composite Behavioral SLO.
13. Evaluator ignores hidden evidence that was not retrieved by tool calls.
14. Payments scenario follows a different valid dependency path.
15. Insufficient-evidence scenario avoids overclaiming.
16. FastAPI comparison endpoint returns both traces and evaluations.
17. Unknown scenarios return a clear 404.

## 20. Developer Commands

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
- `make demo` runs the baseline vs candidate comparison from CLI.
- `make test` runs backend, action, chat, evaluator, seed, and API tests.

## 21. Waterfall Build Plan

### Phase 1: Requirements Freeze

Deliverables:

- PRD accepted as source of truth.
- README outline.
- dependency list finalized.

Acceptance:

- primary investigator, chat/action workflow, reliability layer, scenarios, UI, API, and stack are fixed.

### Phase 2: Data And Contracts

Deliverables:

- SQLite schema and seed SQL.
- Pydantic models.
- repository interfaces.
- API schema definitions.

Acceptance:

- `make seed` creates valid replay DB.
- model validation tests pass.

### Phase 3: Investigator Backend

Deliverables:

- SQLAlchemy repository.
- read tools.
- action tools.
- autonomous investigator.
- incident-scoped chat continuation.
- action confirmation and replay mutation.
- post-action verification.

Acceptance:

- backend tests pass.
- autonomous investigation and confirmed sandbox action flow work.

### Phase 4: Reliability Backend

Deliverables:

- baseline and candidate investigator configurations.
- behavioral evaluator.
- comparison endpoint.
- persisted traces and evaluations.

Acceptance:

- comparison endpoint returns expected PASS/FAIL split.
- evaluator consumes only observed trace evidence plus expected outcome.

### Phase 5: Frontend

Deliverables:

- AI Incident Investigator workspace.
- scenario selector.
- run investigation action.
- hypothesis and timeline UI.
- evidence charts.
- topology/trajectory graph.
- RCA/mitigation/verification panels.
- incident-scoped chat/action panel.
- Reliability / Compare Versions view.
- Behavioral SLO reveal.

Acceptance:

- primary investigator demo works from the UI.
- reliability comparison remains available as secondary workflow.

### Phase 6: Hardening

Deliverables:

- final README.
- screenshots or demo notes.
- lint/format pass.
- fresh-run verification.

Acceptance:

- full demo runs locally.
- five-minute presentation path is documented.
- no real infrastructure credentials are required for replay tools or actions.

## 22. Out Of Scope

The prototype does not include:

- production authentication;
- real infrastructure remediation;
- external observability integrations;
- live telemetry ingestion;
- multi-tenant data storage;
- deployment automation;
- model fine-tuning;
- long-term general-purpose chat memory;
- production alerting or ticketing;
- autonomous execution of state-changing production actions;
- a generalized agent evaluation platform beyond the incident replay reliability layer.

## 23. Final Acceptance Criteria

The project is complete when:

1. `make install`, `make seed`, `make test`, and the UI run commands work on a clean checkout.
2. The React UI opens to the AI Incident Investigator workspace, not the reliability comparison.
3. The primary flow shows incident context, hypotheses, tool calls, evidence interpretation, RCA or abstention, mitigation, and verification.
4. Incident-scoped chat can answer follow-up questions from existing evidence or invoke read tools.
5. State-changing action requests produce explicit proposals and require confirmation.
6. Confirmed actions mutate only replay sandbox state and trigger verification.
7. The Reliability / Compare Versions view runs baseline and candidate configurations against the same replay.
8. Tool calls are captured in `InvestigationTrace`.
9. The evaluator consumes only observed trace evidence plus expected outcome.
10. The comparison shows correct RCA with passing behavior for baseline mode.
11. The comparison shows correct RCA with failing behavior for candidate mode.
12. README explains the primary investigator product, reliability layer, architecture, run commands, limitations, and next steps.

## 24. Engineering Handoff

Implementation work should optimize for this story order:

```text
First:
AI investigator helps an on-call engineer investigate, act, and verify.

Then:
Reliability layer shows how teams prevent agent regressions.
```

### Investigator Slice

Required behavior:

- receive incident context;
- form hypotheses;
- invoke read tools;
- summarize evidence;
- produce RCA or abstention;
- recommend mitigation;
- support incident-scoped chat follow-up;
- propose sandbox actions;
- require confirmation for state-changing tools;
- verify action outcome.

### Reliability Slice

Required behavior:

- run baseline and candidate configurations against the same incident replay and same available evidence;
- show RCA accuracy first for both configurations;
- reveal Behavioral SLO results after RCA accuracy;
- let the trajectory explain why the candidate regressed;
- expose additional scenarios so the implementation does not appear fitted to one incident type.

### Evaluation Slice

Required behavior:

- consume `InvestigationTrace + ExpectedOutcome`;
- report RCA accuracy separately while including it in the composite Behavioral SLO;
- score only retrieved tool-call evidence;
- avoid reading SQLite, seed SQL, hidden evidence, or replay repositories for groundedness;
- keep reasons concise and evidence-oriented;
- keep configuration labels out of evaluator reasons so the evaluator does not prejudge baseline or candidate.
