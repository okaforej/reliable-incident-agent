# Reliable Incident Agent

Reliable Incident Agent shows how to evaluate an autonomous incident investigator
by the quality of its investigation, not only its final answer.

> **One real LLM autonomously investigates a deterministic incident replay using
> realistic observability tools.**

The replay, tool results, action state, and evaluator are deterministic. The LLM
chooses its hypotheses, tools, evidence, and conclusion.

## Product

### Incident Investigator

An on-call engineer can:

1. Select an active incident and review agent-safe context.
2. Start a real OpenAI-backed investigation.
3. Watch hypotheses, tool calls, and evidence stream into a durable timeline.
4. Inspect an evidence-backed RCA or a defensible abstention.
5. Ask follow-up questions in the same investigation context.
6. Confirm one simulated checkout database-pool rollback and verify recovery.

### Compare Agent Versions

An AI reliability engineer can run baseline and candidate prompt policies against
independent copies of the same replay. The scorecard keeps RCA correctness
separate from the three Behavioral SLO dimensions:

- **Grounding** — claims cite evidence actually retrieved by the agent.
- **Investigation Sufficiency** — the trace distinguishes plausible causes.
- **Tool Efficiency** — the agent stays within budget and avoids waste.

## Architecture

```text
React + Vite
    │ explicit POST actions / read-only GETs / SSE progress
FastAPI
    ├── provider-injected investigator ── OpenAI Responses API
    ├── five deterministic observability tools
    ├── deterministic behavioral evaluator
    └── SQLAlchemy repository ── SQLite replay and run history
```

The investigator initially receives only incident-safe context and tool schemas.
Telemetry is retrieved through tools; expected outcomes remain evaluator-only.
Tests inject a fake model provider, so the default test suite never uses the
network or credentials.

## Quick Start

Prerequisites: Python 3.9+ and Node.js 20+.

Create an ignored `openapi_key.md` file in the repository root containing your
OpenAI API key, then run:

```bash
make run
```

The launcher installs missing dependencies, initializes the replay database when
needed, and starts the API and UI. Open `http://127.0.0.1:5173` and press
`Ctrl-C` to stop both services.

The key is passed only to server-side processes. No model call occurs on page
load or incident selection; live work begins only from an explicit action.
Existing investigation history survives ordinary restarts.

To override the default tool-capable model:

```bash
OPENAI_MODEL=<model> make run
```

## Demo Workflow

1. Select **Checkout latency and intermittent HTTP 503s**.
2. Open the incident context, then click **Start investigation**.
3. Follow the streamed hypotheses, tool purposes, and retrieved evidence.
4. Inspect the RCA and expand the Behavioral SLO details.
5. Ask why an alternative dependency was ruled out.
6. Request the supported rollback, review its exact values, and confirm it.
7. Inspect deterministic recovery verification and the agent's assessment.
8. Open **Compare Agent Versions** and compare both trajectories.

For credential-free demo insurance, `make demo` runs a clearly labelled recorded
fake-provider comparison. It is never substituted for a failed live run.

## Commands

| Command | Purpose |
|---|---|
| `make run` | Install dependencies and start the complete application |
| `make seed` | Reset the local replay database and history |
| `make test` | Run backend and frontend tests without live model calls |
| `make lint` | Run Python lint checks |
| `make build` | Type-check and build the frontend |
| `make demo` | Run the labelled recorded CLI comparison |
| `make live-smoke` | Explicitly opt into one live provider smoke test |

## Repository Layout

```text
app/src/                       React workspace, API client, and UI tests
src/reliable_incident_agent/   FastAPI, investigator, tools, evaluator, replay
data/seeds/                    Deterministic incident replay data
tests/                         Offline backend and contract tests
live_tests/                    Explicitly opt-in provider smoke test
scripts/                       CLI demo entry point
COORDINATION.md                Product and architecture contract
```

## Reliability Boundaries

- The model chooses tool order; no scenario-specific trajectory is scripted.
- Unknown tools, invalid arguments, cross-scenario access, and tool-budget
  exhaustion fail explicitly.
- GET requests never start model work or mutate replay state.
- Progress events and completed results persist in SQLite for reconnection.
- Every investigation and comparison arm receives an isolated replay instance.
- Chat cannot execute actions; the only rollback requires explicit confirmation.
- API or provider failure never falls back silently to fixtures.
- Raw chain-of-thought, evaluator truth, and credentials are never displayed.

## Deliberate Tradeoffs

- The prototype uses deterministic local telemetry rather than live Grafana,
  Prometheus, Loki, or Tempo integrations.
- Investigation work runs in an in-process worker; production would use a durable
  queue with restart recovery.
- The evaluator is deterministic and scenario-calibrated, not a general incident
  correctness oracle.
- Comparison execution is synchronous. Its UI shows honest elapsed progress but
  does not fabricate per-agent streaming events.
- Authentication, tenancy, RBAC, and generalized remediation are out of scope.

See [COORDINATION.md](COORDINATION.md) for the concise architecture contract.
