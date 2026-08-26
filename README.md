# Reliable Incident Agent

**Right answer, right reasons.**

This prototype demonstrates why final RCA accuracy is not enough for incident-investigation agents. Two agents can produce the same correct root cause while taking very different investigative paths. The useful reliability question is whether the agent gathered enough relevant evidence to justify the answer.

## Architecture

```text
Incident
  -> Context-aware investigator
  -> Selective observability tools
  -> Recorded trajectory
  -> RCA
  -> Behavioral SLO evaluation
```

Codex owns the runtime path: `agent/`, `tools/`, `data/`, and `app/`.
Copilot owns behavioral evaluation: `evaluation/`, `evals/`, and `tests/`.

The shared trajectory contract is in `shared/models.py`.

## Run

CLI:

```bash
python run_demo.py --mode reliable
python run_demo.py --mode weak
```

Streamlit, once the UI is present:

```bash
streamlit run app/streamlit_app.py
```

## Design Decisions

- Local synthetic telemetry keeps the demo reliable and focused on agent behavior.
- The investigator receives incident text and tool descriptions, not the hidden expected RCA.
- Tool calls are selective and recorded as structured evidence.
- Behavioral evaluation should measure invariants, not exact golden paths.
- No Grafana, Prometheus, Kubernetes, database, auth, or production deployment is included.

## Limitation

This is a narrow prototype, not a generalized agent-reliability platform. The claim is limited to incident-investigation workflows: trajectory-level behavioral SLIs can expose differences that output-only RCA checks miss.
