# Behavioral Evaluation

The evaluator consumes `shared.models.InvestigationTrace` directly:

```python
from evaluation import evaluate_trace

result = evaluate_trace(trace)
```

`BehavioralEvaluation` exposes `to_dict()` for the UI and contains RCA
correctness, three behavioral SLIs, the composite behavioral SLO, and concise
reasons.

## Implemented SLIs

- **Grounded investigation:** every recognized causal concept in the final RCA
  is visibly supported by a retrieved tool result.
- **Investigation sufficiency:** at least three distinct informative tools span
  at least two evidence families (runtime signals, topology, and change events).
- **Tool efficiency:** at most six calls, with no exact duplicate, unknown, or
  explicitly irrelevant call.

These are behavioral invariants, not a required tool sequence. Different valid
investigation paths can pass.

## Limitations

The evaluator scores observable tool calls and evidence. It does not inspect
hidden chain-of-thought or prove that the model internally reasoned correctly.
The evidence taxonomy and thresholds are deliberately small and fixture-aligned
for this prototype; production use would require versioned policies, calibrated
incident-specific thresholds, and longitudinal evaluation data.