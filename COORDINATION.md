# Reliable Incident Agent Coordination

## Shared Contract

Source of truth: `shared/models.py`

Both runtime and evaluator code must use this minimal trajectory contract:

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
```

Runtime may serialize traces with `InvestigationTrace.to_dict()`.
Evaluators may load traces with `InvestigationTrace.from_dict()`.

Do not add a second trace model. If the evaluator needs more information, add it deliberately here and record the decision below.

## Ownership Boundaries

Codex owns the runtime/product slice:

- `agent/`
- `tools/`
- `data/`
- `app/`
- minimal shared contract in `shared/`

Copilot owns the behavioral-evaluation slice:

- `evaluation/`
- `evals/`
- `tests/`
- evaluation-specific docs

Avoid touching the other engineer's files unless integration requires it.

## Codex Status

- Created the shared trajectory contract in `shared/models.py`.
- Created this coordination file to unblock evaluator work.
- Implemented local incident fixtures in `data/`.
- Implemented structured observability tools in `tools/observability.py`.
- Implemented reliable and weak investigation modes in `agent/investigator.py`.
- Implemented CLI entrypoint in `run_demo.py`.
- Implemented Streamlit demo in `app/streamlit_app.py`.
- Verified:
  - `python3 -m py_compile shared/models.py tools/observability.py agent/investigator.py run_demo.py app/streamlit_app.py`
  - `python3 run_demo.py --incident inc_checkout_db_pool_001 --mode reliable`
  - `python3 run_demo.py --incident inc_checkout_db_pool_001 --mode weak`

## Copilot Status

- Implemented deterministic evaluation in `evaluation/evaluator.py` against
  `shared/models.py`.
- Public API: `from evaluation import evaluate_trace`; pass an
  `InvestigationTrace` and receive a `BehavioralEvaluation` with `to_dict()`.
- Evaluator output:
  - `rca_correct`
  - `grounded`
  - `investigation_sufficient`
  - `tool_efficient`
  - `behavioral_slo_pass`
  - `reasons`
- Added focused adversarial tests plus a real runtime integration test.
- Verified the central comparison on `inc_checkout_db_pool_001`:
  - weak: RCA correct, behavioral SLO fail;
  - reliable: RCA correct, behavioral SLO pass.

## Integration Notes

- The investigator must not receive `expected_root_cause`; that field exists for evaluation only.
- Tool results should remain structured enough for evaluator inspection.
- The runtime should produce at least one strong autonomous trace.
- Fixtures may include weak and strong traces with the same correct RCA to demonstrate: correct answer, wrong reasons.
- Runtime entrypoint: `agent.run_investigation(incident_id: str, mode: str = "reliable") -> InvestigationTrace`.
- Key scenario: `inc_checkout_db_pool_001`.
- Reliable mode gathers checkout health, checkout logs, checkout dependencies, postgres metrics, postgres health, and checkout changes.
- Weak mode inspects one checkout timeout log, then jumps to the same final RCA.
- UI will call Copilot's evaluator if one of these exists:
  - `evaluation.evaluator.evaluate_trace`
  - `evaluation.behavioral.evaluate_behavioral_reliability`
  - `evaluation.evaluate`
  - `evals.evaluator.run_evaluation`
- Groundedness means observable result-to-RCA evidence coverage; it does not
  claim to inspect hidden model reasoning or chain-of-thought.
- Sufficiency requires three distinct informative tools across two evidence
  families. Efficiency permits up to six calls and rejects exact duplicates,
  unknown tools, or results explicitly marked `relevant: false`.
- The Streamlit evaluator discovery already recognizes
  `evaluation.evaluator.evaluate_trace`; no UI adapter is required.

## Decisions

- Keep the shared contract minimal: `InvestigationTrace` plus `ToolCall`.
- Use local synthetic telemetry rather than Grafana, Prometheus, Kubernetes, or databases.
- Evaluate behavioral invariants, not exact golden tool sequences.
- Added `get_metrics` as a fifth tool because postgres saturation is stronger evidence than health text alone.
- Keep RCA correctness separate from behavioral SLO status so a supported but
  incorrect conclusion and a lucky correct conclusion remain distinguishable.
