# Reliable Incident Agent

Reliable Incident Agent is a local incident-replay prototype for reliability
engineering of incident agents. Its thesis is simple: final RCA correctness is
not enough. A candidate model, prompt, tool, or workflow change can preserve the
same correct root cause while regressing in how the agent investigates.

The demo compares a baseline investigator configuration with a candidate
configuration on a deterministic DB-pool replay, then includes two additional
replay scenarios to show the runtime is not hard-coded to one incident shape:

- `checkout_db_pool_exhaustion`: DB saturation after checkout pool config change.
- `payments_gateway_timeout`: downstream payments/gateway timeout path.
- `insufficient_frontend_evidence`: partial evidence where the agent should not overclaim.

```text
Baseline:
  RCA correct
  Evidence grounded and sufficient
  Behavioral SLO PASS

Candidate:
  RCA correct
  Evidence insufficient
  Behavioral SLO FAIL
```

Both agents should produce the same RCA:

```text
Checkout latency was caused by postgres connection exhaustion after checkout deployed a database pool max_open_connections change from 20 to 80.
```

## Architecture

The system is intentionally local and deterministic.

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

The replay database stores incident context, service topology, metrics, logs,
changes, expected outcomes, investigation runs, tool calls, and evaluations.
The investigator reads incident evidence only through observability tools.
The evaluator receives only `InvestigationTrace + ExpectedOutcome`, so hidden
seed evidence cannot mask a behavioral regression.

## Stack

- SQLite for deterministic local replay storage.
- SQLAlchemy Core for the repository boundary.
- Pydantic for request, response, trace, and evaluation contracts.
- FastAPI for the backend API and OpenAPI documentation.
- React + Vite for the incident command center.
- shadcn/ui for compact enterprise UI components.
- TanStack Query for frontend server state.
- React Flow for topology and trajectory graphs.
- Recharts for incident metrics and evidence timelines.
- pytest for backend, evaluator, and API tests.
- Ruff for Python linting and formatting.
- Makefile targets for repeatable local commands.

## Run Commands

```bash
make install
make seed
make api
make app
make demo
make test
make lint
```

Expected command behavior:

- `make seed` creates `var/replays.sqlite`.
- `make api` starts the FastAPI service.
- `make app` starts the React UI.
- `make demo` runs the baseline vs candidate comparison from the CLI.
- `make test` runs backend, evaluator, seed, and API contract tests.

## Demo Path

1. Start the backend with `make api` and the frontend with `make app`.
2. Open the incident command center and select `checkout_db_pool_exhaustion`.
3. Run the comparison and pause on the output-only panel: Version A RCA PASS,
   Version B RCA PASS, identical final RCA.
4. State the apparent output-layer conclusion: the versions look equivalent.
5. Click `Reveal SLO`: Version A passes the Behavioral SLO and Version B fails.
6. Inspect Version B: it reached the correct RCA from checkout-local timeout
   logs without enough postgres, change, and alternative-dependency evidence.
7. Inspect Version A: it traversed checkout dependencies, observed postgres
   saturation, retrieved the checkout DB pool change, and ruled out collateral
   payments symptoms.
8. Switch to `payments_gateway_timeout` to show a different valid investigation
   path through the payments dependency.
9. Switch to `insufficient_frontend_evidence` to show the agent avoiding an
   unjustified RCA when the replay lacks conclusive evidence.

Two-minute talk track:

- 0:00 - Reliability engineering for incident agents asks whether a new model,
  prompt, or tool configuration stayed reliable, not only whether it produced
  the same final answer.
- 0:20 - Run the deterministic replay comparison.
- 0:40 - Show RCA parity: both configurations produce the correct final RCA, so
  output-only evaluation says they are equivalent.
- 1:00 - Reveal Behavioral SLOs: the baseline passes and the candidate fails.
- 1:25 - Explain the trajectory gap: one investigation gathered distinguishing
  operational evidence; the other took a plausible shortcut.
- 1:50 - Switch scenarios to prove the replay/evaluator is not hard-coded to one
  incident class.

No OpenAI API key is required for the core demo. FastAPI exposes the local
OpenAPI contract at `/openapi.json`; the investigator itself is deterministic
over SQLite replay evidence so reviewers can reproduce every run without
external credentials.

## Expected Backend Interfaces

The tests assume the PRD public contract below. If implementation names differ,
update only the small import shims in `tests/conftest.py`.

Pydantic models in `src/reliable_incident_agent/models.py`:

```python
ToolCall(
    sequence: int,
    tool_name: str,
    arguments: dict,
    result: dict,
)

InvestigationTrace(
    incident_id: str,
    incident_description: str,
    tool_calls: list[ToolCall],
    final_root_cause: str,
)

ExpectedOutcome(root_cause: str)

BehavioralEvaluation(
    rca_correct: bool,
    grounded: bool,
    investigation_sufficient: bool,
    tool_efficient: bool,
    behavioral_slo_pass: bool,
    reasons: list[str],
)

InvestigationRequest(
    scenario_id: str,
    mode: Literal["baseline", "candidate"],
)

InvestigationResponse(
    run_id: str,
    trace: InvestigationTrace,
    evaluation: BehavioralEvaluation,
)
```

Runtime and API interfaces:

- `reliable_incident_agent.investigator.run_investigation(scenario_id, mode)`
  returns `InvestigationTrace`.
- `reliable_incident_agent.evaluator.evaluate_trace(trace, expected_outcome)`
  returns `BehavioralEvaluation`.
- `reliable_incident_agent.api.app` is a FastAPI app.
- `GET /comparisons/{scenario_id}` returns:

```json
{
  "scenario_id": "checkout_db_pool_exhaustion",
  "baseline": {
    "trace": {},
    "evaluation": {}
  },
  "candidate": {
    "trace": {},
    "evaluation": {}
  }
}
```

## Test Coverage

The contract tests cover:

- SQLite seed DB exists and includes required tables plus scenario data.
- Pydantic validation for trace, evaluation, request, and response models.
- Baseline and candidate investigations produce the same expected RCA.
- Baseline investigation passes the behavioral SLO.
- Candidate investigation fails the behavioral SLO.
- Incorrect RCA fails correctness while behavioral fields remain independently
  reported.
- Evaluator ignores hidden evidence that was not retrieved by tool calls.
- FastAPI comparison endpoint returns both traces and evaluations.

## Limitations

- The prototype is local-only and does not ingest live telemetry.
- It uses three small deterministic incident scenarios rather than live data.
- It does not include production authentication, authorization, tenancy,
  alerting, ticketing, or deployment automation.
- The evaluator is a behavioral demo evaluator, not a general incident
  correctness oracle.
- The UI is designed for a five-minute interview demo, not a production
  incident-management workflow.
