# Reliable Incident Agent

Reliable Incident Agent is a local incident-investigation prototype with a
deterministic replay and reliability layer. Its thesis is simple: final RCA correctness is
not enough. A model, prompt, tool, or workflow change must be assessed by the
evidence-gathering behavior that produced the answer, not only by the final
answer text.

The product centers on a real OpenAI-backed investigator working against a
deterministic replay. The primary demo is investigator-first: select an active
incident, watch durable investigation milestones and model-selected observability
tools stream into the timeline, inspect the RCA or abstention, ask a
follow-up, confirm the single safe simulated rollback, and inspect both the
deterministic recovery verdict and the investigator's evidence-backed
assessment. The secondary
comparison view runs baseline and candidate prompt configurations over the same
replay and reports actual outcomes plus Behavioral SLOs.

- `checkout_latency_spike`: checkout latency and intermittent HTTP 503s.
- `payment_submission_failures`: elevated payment submission failures.
- `frontend_error_spike`: intermittent HTTP 500s on frontend product pages.

## Architecture

The replay and evaluator are deterministic; the investigator is provider-backed
and non-deterministic in live mode.

```text
React Incident Command Center
  -> FastAPI service
  -> accepted run + persisted SSE progress events
  -> provider-injected investigator runtime
  -> OpenAI Responses API custom tools
  -> SQLAlchemy replay repository
  -> SQLite replay database

InvestigationTrace
  -> behavioral evaluator
  -> BehavioralEvaluation
  -> API response
  -> UI scorecard and comparison
```

The replay database stores agent-safe incident context, service topology,
metrics, logs, changes, isolated replay instances, chat messages, action proposals,
investigation run state, ordered progress events, tool calls, and evaluations. The investigator reads incident
evidence only through five observability tools. Expected outcomes are loaded
only after the trace completes and are visible only to the evaluator.

## Stack

- SQLite for deterministic local replay storage.
- OpenAI Responses API for the live investigator provider.
- SQLAlchemy Core for the repository boundary.
- Pydantic for request, response, trace, and evaluation contracts.
- FastAPI for the backend API and OpenAPI documentation.
- React + Vite for the incident command center.
- Small reusable React primitives for compact enterprise UI components.
- TanStack Query for frontend server state.
- pytest for backend, evaluator, and API tests.
- Ruff for Python linting and formatting.
- Makefile targets for repeatable local commands.

## Run Commands

For the complete local application, keep `openapi_key.md` in the repository
root and run one command:

```bash
make run
```

This installs dependencies, reads the ignored key file, defaults the model to
`gpt-5.6-terra`, initializes a missing replay database, and starts both the API and
UI. Open `http://127.0.0.1:5173` and press `Ctrl-C` when finished. The key is
injected only into server-side child processes and is never sent to the browser.
Existing investigation history is preserved across ordinary restarts; run
`make seed` when you explicitly want a clean deterministic reset.

Individual commands remain available:

```bash
make demo
make test
make live-smoke
make lint
```

Expected command behavior:

- `make run` installs, initializes when needed, and starts the complete live application using
  `openapi_key.md`.
- `make seed` replaces `var/replays.sqlite` with a clean deterministic replay.
- `make api` installs and starts only the FastAPI service using the same key
  file.
- `make app` starts the React UI.
- `make demo` runs a clearly labelled recorded fake-provider comparison from
  the CLI; use `PYTHONPATH=src .venv/bin/python scripts/run_demo.py --live` for
  explicit live OpenAI-backed execution.
- `make live-smoke` installs dependencies, reads the same key file, and runs an
  opt-in live provider smoke test. It is excluded from `make test`.
- `make test` runs backend, evaluator, seed, and API contract tests.
- Live Responses calls use stateless continuation with `store: false`, including
  encrypted reasoning items, so the tool loop works with Zero Data Retention.

## Demo Path

1. Run `make run`, then open `http://127.0.0.1:5173`.
2. Select an incident, review its operational context, and note the explicit
   `Replay environment · deterministic telemetry` badge.
3. Click **Start investigation**. Watch the LLM choose observability tools as
   persisted milestones and expandable evidence stream into the timeline, then
   produce an RCA or abstention.
4. Ask an incident-scoped follow-up question in the same run.
5. If the checkout rollback is proposed, confirm it and inspect the
   application-owned telemetry verdict plus the investigator's recovery
   assessment.
6. Run the secondary comparison to inspect actual baseline/candidate outcomes
   with RCA correctness shown separately from Grounding, Investigation
   Sufficiency, Tool Efficiency, and Behavioral SLO.

For emergency reproducibility without network credentials, `make demo` runs a
labelled recorded fake-provider comparison. That path is not the live primary
implementation and should not be presented as evidence that live runs always
produce identical RCAs or fixed SLO outcomes.

## Expected Backend Interfaces

The tests assume the PRD public contract below. If implementation names differ,
update only the small import shims in `tests/conftest.py`.

Pydantic models in `src/reliable_incident_agent/models.py`:

```python
ToolCall(
    sequence: int,
    tool_name: str,
    purpose: str,
    arguments: dict,
    result: dict,
    evidence_ids: list[str],
    status: Literal["ok", "error"],
    duration_ms: int,
)

InvestigationTrace(
    incident_id: str,
    incident_description: str,
    agent_config_id: Literal["baseline", "candidate"],
    prompt_version: str,
    tool_schema_version: str,
    model: str,
    hypotheses: list[str],
    tool_calls: list[ToolCall],
    final_result: InvestigationFinalResult,
    provider_metadata: ProviderMetadata,
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

InvestigationAccepted(
    run_id: str,
    scenario_id: str,
    status: Literal["queued", "running"],
)

InvestigationRunStatus(
    run_id: str,
    scenario_id: str,
    status: Literal["queued", "running", "completed", "failed"],
    response: InvestigationResponse | None,
    error: str | None,
)
```

Runtime and API interfaces:

- `reliable_incident_agent.investigator.run_investigation(scenario_id, mode)`
  returns `InvestigationTrace` and uses the injected provider or live OpenAI
  provider.
- `reliable_incident_agent.evaluator.evaluate_trace(trace, expected_outcome)`
  returns `BehavioralEvaluation`.
- `reliable_incident_agent.api.app` is a FastAPI app.
- `POST /investigations` explicitly starts one investigation and immediately
  returns `202 Accepted` with its run ID.
- `GET /investigations/{run_id}` reads the run status and, after completion,
  the canonical response, persisted follow-up conversation, and confirmed
  action/verification state without starting work.
- `GET /investigations/{run_id}/events` streams persisted progress events using
  Server-Sent Events and supports reconnect through event IDs.
- `POST /investigations/{run_id}/messages` continues incident chat.
- `POST /investigations/{run_id}/actions/{proposal_id}/confirm` confirms the
  single checkout rollback.
- `POST /comparisons` explicitly creates a baseline/candidate comparison.
- `GET /comparisons` lists persisted comparison summaries for read-only history.
- `GET /comparisons/{comparison_id}` retrieves a persisted comparison:

```json
{
  "scenario_id": "checkout_latency_spike",
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
- Provider-injected investigations execute model-selected tool calls.
- OpenAI Responses continuation preserves `previous_response_id` and
  `function_call_output` linkage.
- OpenAI function tool schemas are strict.
- Non-runtime provider failures return honest 503 API responses without secret
  leakage.
- Abstention grounding requires relevant negative evidence rather than an
  unrelated empty result.
- Expected outcome never enters model context.
- Active replay does not expose post-action recovery evidence.
- Action proposal lifecycle fields are server-owned and mutation is confirmed,
  fixed-target, idempotent, and verified from post-action telemetry.
- Every investigation and comparison arm gets an independent active replay
  instance, so a rollback cannot contaminate another run.
- Confirmation leaves the original investigation trace and evaluation
  immutable; verification calls and the recovery assessment belong to the
  action result.
- A recovery-assessment provider failure after mutation returns the completed
  action and deterministic verdict with an explicit assessment error.
- Incorrect RCA fails correctness while behavioral fields remain independently
  reported.
- Evaluator ignores hidden evidence that was not retrieved by tool calls.
- API `GET` requests are read-only and comparison creation is explicit `POST`.
- Async start, ordered progress events, SSE reconnect, canonical completion,
  sanitized terminal failure, and exactly-once provider execution.

## Limitations

- The prototype is local-only and does not ingest live telemetry.
- It uses three small deterministic incident scenarios rather than live data.
- It does not include production authentication, authorization, tenancy,
  alerting, ticketing, or deployment automation.
- The evaluator uses deterministic, scenario-calibrated rules for this replay
  set; it is not a general incident-correctness oracle.
- The UI is designed for the ten-minute investigator-first demo contract, not a
  production incident-management workflow.
- Investigation execution uses an in-process worker. Runs and events survive a
  browser disconnect, but production deployment would add a durable job worker
  and restart recovery.
- Production durability would require transaction or outbox recovery for a
  process crash between replay mutation and action-result persistence.
