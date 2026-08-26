# Reliable Incident Agent Coordination

## Goal

Build a polished local prototype for the Grafana AI/ML take-home:

> **Right answer, right reasons.**

The demo must show that final RCA accuracy is not enough. Two investigation trajectories can reach the same correct RCA, while only one gathered enough relevant evidence to be operationally reliable.

## Architecture

Use **Incident Replay** as the enterprise-grade abstraction:

```text
Streamlit UI
  -> run_investigation(...)
  -> observability tools
  -> Incident Replay repository
  -> deterministic JSON scenario

InvestigationTrace
  -> evaluate_trace(...)
  -> BehavioralEvaluation
```

The implementation can stay simple: local Python, JSON fixtures, deterministic evaluation.

The architectural story is:

```text
Prototype:  Agent -> tools -> Incident Replay repository -> JSON
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

data/
  scenarios/
    checkout_db_pool_exhaustion/
      incident.json
      metrics.json
      logs.json
      changes.json
      topology.json
      expected.json

src/
  reliable_incident_agent/
    __init__.py
    models.py
    replay.py
    tools.py
    investigator.py
    evaluator.py

app/
  streamlit_app.py

scripts/
  run_demo.py

tests/
  test_evaluator.py
  test_runtime_evaluation.py
```

Use one Python package under `src/reliable_incident_agent/`. Do not create separate top-level packages like `agent/`, `tools/`, `shared/`, or `evaluation/`.

## Minimal Open-Source Stack

Use these because they add polish without infrastructure risk:

- **Streamlit** for the local demo UI.
- **Pydantic** for `models.py` contracts and fixture validation.
- **Altair** for one or two incident evidence charts.
- **pytest** or `unittest` for deterministic tests.
- **Makefile** for `make demo`, `make test`, and `make app`.

Optional:

- **Rich** for a clean CLI comparison table.

Do not add FastAPI, Docker, a database, live Grafana/Prometheus/Loki, OpenTelemetry backends, Phoenix, Langfuse, or DeepEval unless the core demo is already working and the addition is clearly non-fragile.

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

## Evaluation Rule

Evaluation must score only what the agent actually observed in `InvestigationTrace.tool_calls`.

Do not let evaluator logic read telemetry fixtures, replay repositories, hidden evidence, or scenario files to decide whether the agent was grounded. If the agent did not retrieve evidence through a tool call, the evaluator must treat that evidence as unobserved.

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

## Scope Boundaries

Do not build:

- generic chatbot;
- full RCA platform;
- production Grafana integration;
- live telemetry stack;
- database;
- auth;
- Slack or ticketing integration;
- multiple scenarios before the first one is excellent.

Keep the demo reliable, readable, and runnable locally.
