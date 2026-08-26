# Reliable Incident Agent Coordination

## Current Direction

We are in cleanup and convergence mode.

The prototype should look enterprise-grade by presenting a clean architecture, not by adding fragile infrastructure. The implementation should converge around an **Incident Replay** abstraction:

```text
UI / Demo
  -> Investigator runtime
  -> Tool interfaces
  -> Incident Replay repository
  -> Deterministic JSON fixtures

InvestigationTrace
  -> Behavioral evaluator
  -> Behavioral SLO result
```

The Staff-level framing:

> Deterministic incident replays let us compare agent versions and trajectories against identical operational conditions. Behavioral evaluation then asks whether the agent chose to obtain and use the right evidence, not merely whether the right evidence existed somewhere in the dataset.

## Scope Discipline

Optimize for a polished, reliable local demo.

Do not add:

- external databases;
- streaming telemetry;
- Prometheus, Loki, Tempo, Grafana, or OpenTelemetry backends;
- Docker Compose infrastructure;
- authentication;
- persistence beyond local fixtures;
- duplicate agent implementations;
- broad eval platforms.

Add an open-source tool only if it improves demo clarity, startup reliability, or enterprise polish with low implementation cost.

## Preferred Open-Source Stack

Use this stack unless there is a concrete reason not to:

- **Python dataclasses or Pydantic** for shared contracts and validation.
- **Streamlit** for the demo UI if already working.
- **pytest** or `unittest` for deterministic smoke/evaluator tests.
- **Ruff** for formatting/linting if time permits.
- **Rich** for a polished CLI trace view if the CLI becomes part of the demo.
- **Altair/Plotly** only for small evidence visuals that clarify the incident timeline.

Optional but not required:

- **FastAPI** only if a service boundary already exists or can be added without rewriting the working Streamlit flow.
- **Phoenix, Langfuse, or OpenLIT** only if working quickly and used as trace visualization, not as a required runtime dependency.
- **DeepEval** only if it wraps our existing deterministic behavioral checks without hiding the simple thesis.

Default decision: keep JSON fixtures, repository/tool interfaces, deterministic evaluation, and the existing local UI.

## Repository Shape

Target structure:

```text
.
README.md
COORDINATION.md
requirements.txt
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

Use one Python package under `src/` instead of recreating separate top-level packages such as `agent/`, `tools/`, `shared/`, and `evaluation/`. That keeps the polished implementation easy to inspect and reduces import drift.

## Shared Contract

Source of truth should be `src/reliable_incident_agent/models.py`.

Use Pydantic if available; dataclasses are acceptable if they keep the demo simpler. Either way, keep the contract small:

```python
ToolCall:
    sequence: int
    tool_name: str
    arguments: dict
    result: dict

InvestigationTrace:
    incident_id: str
    incident_description: str
    expected_root_cause: str
    tool_calls: list[ToolCall]
    final_root_cause: str

BehavioralEvaluation:
    rca_correct: bool
    grounded: bool
    investigation_sufficient: bool
    tool_efficient: bool
    behavioral_slo_pass: bool
    reasons: list[str]
```

Keep this intentionally small. Do not create a second trace schema or a package-local duplicate.

`expected_root_cause` is evaluation-only metadata. The investigator must not receive it in its prompt or tool context.

## Ownership Boundaries

Codex is lead for architecture, cleanup review, and coordination.

Runtime/demo implementation scope:

- `data/scenarios/`
- `src/reliable_incident_agent/replay.py`
- `src/reliable_incident_agent/tools.py`
- `src/reliable_incident_agent/investigator.py`
- `app/`
- `scripts/run_demo.py`

Evaluation implementation scope:

- `src/reliable_incident_agent/evaluator.py`
- `tests/`

Shared contract scope:

- `src/reliable_incident_agent/models.py`

Only one engineer should edit `models.py` at a time. If either side needs a contract change, record it here before coding against it.

## Guide For Copilot

Convergence rule: implement one polished vertical slice only.

Copilot should implement against the package structure above and consume only the public runtime/contract APIs.

Thesis to preserve:

> Reliable incident agents should be evaluated on both final RCA correctness and observable investigation behavior.

The demo must show two traces for the same incident with the same correct RCA:

- a weak/lucky trajectory that fails behavioral SLOs;
- a well-supported trajectory that passes behavioral SLOs.

Critical rule:

> Evaluation must operate on what the agent actually observed, not on all telemetry available in the replay fixture.

Do not query JSON fixtures, replay repositories, telemetry files, or hidden expected evidence from evaluator logic. If the agent did not call a tool and retrieve a result, the evaluator should treat that evidence as unobserved.

Runtime public API:

```python
run_investigation(
    scenario_id: str,
    mode: Literal["weak", "reliable"],
) -> InvestigationTrace
```

Evaluator public API:

```python
evaluate_trace(
    trace: InvestigationTrace,
    expected: ExpectedOutcome,
) -> BehavioralEvaluation
```

The UI should import only those two APIs.

Preferred behavioral dimensions:

- **Grounded Investigation:** retrieved tool results visibly support the RCA.
- **Investigation Sufficiency:** retrieved evidence distinguishes the RCA from plausible alternatives.
- **Tool Efficiency:** no redundant, irrelevant, or excessive calls.

Do not require an exact golden sequence. Valid trajectories may differ.

Required comparison case:

```text
Weak trajectory:
  RCA correct
  Evidence weak/insufficient
  Behavioral SLO FAIL

Reliable trajectory:
  RCA correct
  Evidence grounded and sufficient
  Behavioral SLO PASS
```

This is the core demo. Protect it.

Tests must prove:

- weak trace: RCA correct, behavioral SLO fails;
- reliable trace: RCA correct, behavioral SLO passes;
- incorrect RCA is reported separately from behavior quality.

## Cleanup Guidance

Remove or avoid:

- unused framework scaffolding;
- duplicate data loaders;
- direct fixture reads from the agent or evaluator;
- hard-coded “always call logs -> metrics -> changes” paths;
- UI decoration that does not clarify the experiment;
- dependencies that are not required to run the demo.
- real API keys or local secrets.

Keep or add:

- one command to run the demo;
- one command to run tests;
- deterministic fixtures;
- clear repository/tool boundaries;
- side-by-side weak vs reliable comparison;
- concise README explaining Incident Replay and behavioral SLOs.
- a small `Makefile` if it improves local ergonomics.
- Altair charts only if they clarify the incident evidence timeline.

## Lead Decisions

- Use **Incident Replay over JSON** as the enterprise-grade abstraction.
- Keep the implementation local and deterministic.
- Prefer internal repository/tool boundaries over adding FastAPI.
- Do not introduce live telemetry infrastructure.
- Evaluation is trajectory-only.
- Best minimal polish stack: **Streamlit + Pydantic + Altair + pytest/unittest + Makefile**, optional **Rich** for CLI tables.
- The final demo should communicate: **right answer is not enough; right answer plus right investigative behavior is reliable.**
