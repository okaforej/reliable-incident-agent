# Reliable Incident Agent

Reliable Incident Agent is a local incident-replay prototype for evaluating
agentic incident investigations. Its thesis is simple: final RCA correctness is
not enough. An incident agent can guess the right root cause through a weak
trajectory, while a reliable agent gathers evidence that supports and
distinguishes the answer.

The demo compares weak and reliable behaviors on a deterministic DB-pool replay,
then includes two additional replay scenarios to show the runtime is not
hard-coded to one incident shape:

- `checkout_db_pool_exhaustion`: DB saturation after checkout pool config change.
- `payments_gateway_timeout`: downstream payments/gateway timeout path.
- `insufficient_frontend_evidence`: partial evidence where the agent should not overclaim.

```text
Weak agent:
  RCA correct
  Evidence insufficient
  Behavioral SLO FAIL

Reliable agent:
  RCA correct
  Evidence grounded and sufficient
  Behavioral SLO PASS
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
The investigator must read incident evidence only through observability tools.
The evaluator receives only `InvestigationTrace + ExpectedOutcome`, so hidden
seed evidence cannot rescue a weak investigation.

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
- `make demo` runs the weak vs reliable comparison from the CLI.
- `make test` runs backend, evaluator, seed, and API contract tests.

## Demo Path

1. Start the backend with `make api`.
2. Start the frontend with `make app`.
3. Open the incident command center.
4. Select `checkout_db_pool_exhaustion`.
5. Run the comparison.
6. Show that both agents return the same RCA.
7. Inspect the weak trajectory: one or two plausible tool calls, correct RCA,
   insufficient evidence, behavioral SLO fail.
8. Inspect the reliable trajectory: checkout symptoms, dependency traversal to
   postgres, postgres connection saturation, checkout DB pool config change,
   collateral payments symptoms ruled out, behavioral SLO pass.
9. Use the SLO panel to explain the core distinction: answer correctness is
   reported separately from investigation reliability.
10. Switch to `payments_gateway_timeout` to show a different valid path through
    the payments dependency.
11. Switch to `insufficient_frontend_evidence` to show the agent avoiding an
    unjustified RCA when the replay lacks conclusive evidence.

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
    mode: Literal["weak", "reliable"],
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
  "weak": {
    "trace": {},
    "evaluation": {}
  },
  "reliable": {
    "trace": {},
    "evaluation": {}
  }
}
```

## Test Coverage

The contract tests cover:

- SQLite seed DB exists and includes required tables plus scenario data.
- Pydantic validation for trace, evaluation, request, and response models.
- Weak and reliable investigations produce the same expected RCA.
- Weak investigation fails the behavioral SLO.
- Reliable investigation passes the behavioral SLO.
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
