"""Minimal Streamlit demo for the Reliable Incident Agent take-home."""

from __future__ import annotations

import importlib
import inspect
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from shared import InvestigationTrace, ToolCall
except Exception:  # pragma: no cover - keeps UI useful during early scaffolding.
    InvestigationTrace = None
    ToolCall = None


FALLBACK_INCIDENTS = [
    {
        "incident_id": "checkout-latency",
        "incident_description": (
            "Checkout API p95 latency spiked after a deploy. Error budget burn "
            "is elevated for the checkout service."
        ),
        "expected_root_cause": "Cache client timeout regression after deploy.",
    },
    {
        "incident_id": "payments-errors",
        "incident_description": (
            "Payment authorization errors increased across one region while "
            "dependency dashboards show intermittent gateway failures."
        ),
        "expected_root_cause": "Regional payment gateway instability.",
    },
]


RUNTIME_MODULES = (
    "agent.runtime",
    "agent.investigator",
    "agent",
)
INCIDENT_MODULES = (
    "data.incidents",
    "agent.runtime",
    "agent.investigator",
)
EVALUATOR_MODULES = (
    "evaluation.evaluator",
    "evaluation.behavioral",
    "evaluation",
    "evals.evaluator",
)


def import_first(module_names: tuple[str, ...]) -> Any | None:
    for name in module_names:
        try:
            return importlib.import_module(name)
        except Exception:
            continue
    return None


def find_callable(module: Any | None, names: tuple[str, ...]) -> Callable[..., Any] | None:
    if module is None:
        return None
    for name in names:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    return None


def as_plain(value: Any) -> Any:
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, dict):
        return {key: as_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [as_plain(item) for item in value]
    return value


def incident_id(incident: Any) -> str:
    data = as_plain(incident)
    if isinstance(data, dict):
        return str(data.get("incident_id") or data.get("id") or data.get("name") or "incident")
    return str(getattr(incident, "incident_id", getattr(incident, "id", "incident")))


def incident_description(incident: Any) -> str:
    data = as_plain(incident)
    if isinstance(data, dict):
        if data.get("incident_description") or data.get("description") or data.get("summary"):
            return str(data.get("incident_description") or data.get("description") or data.get("summary"))
        symptoms = "; ".join(data.get("symptoms", []))
        impact = data.get("customer_impact", "")
        return f"{data.get('title', incident_id(data))}. Impact: {impact}. Symptoms: {symptoms}"
    return str(
        getattr(
            incident,
            "incident_description",
            getattr(incident, "description", getattr(incident, "summary", "")),
        )
    )


def make_trace(incident: Any) -> Any:
    data = as_plain(incident)
    if isinstance(data, dict) and InvestigationTrace and ToolCall:
        return InvestigationTrace(
            incident_id=incident_id(data),
            incident_description=incident_description(data),
            expected_root_cause=str(data.get("expected_root_cause", "")),
            tool_calls=[
                ToolCall(
                    sequence=1,
                    tool_name="load_incident_context",
                    arguments={"incident_id": incident_id(data)},
                    result={"status": "runtime_not_connected", "source": "fallback_ui"},
                )
            ],
            final_root_cause=(
                "Runtime investigator is not connected yet. This placeholder "
                "will be replaced by the agent's final RCA."
            ),
        )
    return {
        "incident_id": incident_id(incident),
        "incident_description": incident_description(incident),
        "expected_root_cause": "",
        "tool_calls": [
            {
                "sequence": 1,
                "tool_name": "load_incident_context",
                "arguments": {"incident_id": incident_id(incident)},
                "result": {"status": "runtime_not_connected", "source": "fallback_ui"},
            }
        ],
        "final_root_cause": (
            "Runtime investigator is not connected yet. This placeholder will "
            "be replaced by the agent's final RCA."
        ),
    }


def load_incidents() -> tuple[list[Any], str]:
    module = import_first(INCIDENT_MODULES)
    loader = find_callable(
        module,
        (
            "list_incidents",
            "load_incidents",
            "get_incidents",
            "available_incidents",
        ),
    )
    if loader:
        try:
            incidents = loader()
            if isinstance(incidents, dict):
                incidents = list(incidents.values())
            incidents = list(incidents)
            if incidents:
                return incidents, f"Loaded from `{module.__name__}.{loader.__name__}`."
            return FALLBACK_INCIDENTS, (
                f"Using fallback incidents; `{module.__name__}.{loader.__name__}` "
                "returned no incidents."
            )
        except Exception as exc:
            return FALLBACK_INCIDENTS, f"Using fallback incidents; loader failed: `{exc}`."
    return FALLBACK_INCIDENTS, "Using fallback incidents until `data/` or `agent/` exposes a loader."


def call_with_supported_args(func: Callable[..., Any], incident: Any, **extra: Any) -> Any:
    params = inspect.signature(func).parameters
    candidates = {
        "incident": incident,
        "incident_id": incident_id(incident),
        "incident_description": incident_description(incident),
        **extra,
    }
    kwargs = {
        name: value
        for name, value in candidates.items()
        if name in params
    }
    if kwargs:
        return func(**kwargs)
    try:
        return func(incident)
    except TypeError:
        return func(incident_id(incident))


def investigate(incident: Any, mode: str = "reliable") -> tuple[Any, str]:
    module = import_first(RUNTIME_MODULES)
    runner = find_callable(
        module,
        (
            "investigate_incident",
            "run_investigation",
            "investigate",
            "run",
        ),
    )
    if runner:
        try:
            return call_with_supported_args(runner, incident, mode=mode), (
                f"Trace generated by `{module.__name__}.{runner.__name__}`."
            )
        except Exception as exc:
            return make_trace(incident), f"Using fallback trace; runtime failed: `{exc}`."
    return make_trace(incident), "Using fallback trace until the runtime investigator is available."


def evaluate_trace(trace: Any) -> tuple[Any | None, str]:
    module = import_first(EVALUATOR_MODULES)
    evaluator = find_callable(
        module,
        (
            "evaluate_trace",
            "evaluate_behavioral_reliability",
            "evaluate",
            "run_evaluation",
        ),
    )
    if evaluator:
        try:
            return evaluator(trace), f"Evaluator result from `{module.__name__}.{evaluator.__name__}`."
        except Exception as exc:
            try:
                return evaluator(as_plain(trace)), (
                    f"Evaluator result from `{module.__name__}.{evaluator.__name__}`."
                )
            except Exception:
                return None, f"Evaluator found but failed: `{exc}`."
    return None, "Evaluator not connected yet."


def trace_field(trace: Any, field: str, default: Any = None) -> Any:
    data = as_plain(trace)
    if isinstance(data, dict):
        return data.get(field, default)
    return getattr(trace, field, default)


def render_tool_timeline(trace: Any) -> None:
    calls = trace_field(trace, "tool_calls", []) or []
    if not calls:
        st.info("No tool calls captured yet.")
        return

    for index, call in enumerate(calls, start=1):
        data = as_plain(call)
        sequence = data.get("sequence", index) if isinstance(data, dict) else index
        name = data.get("tool_name", "tool") if isinstance(data, dict) else str(call)
        with st.expander(f"{sequence}. {name}", expanded=index == 1):
            if isinstance(data, dict):
                st.caption("Arguments")
                st.json(data.get("arguments", {}))
                st.caption("Result")
                st.json(data.get("result", {}))
            else:
                st.write(data)


def render_behavioral_reliability(trace: Any) -> None:
    result, source = evaluate_trace(trace)
    st.caption(source)
    if result is None:
        st.info(
            "Behavioral reliability results will appear here when an evaluator "
            "module exposes `evaluate_trace`, `evaluate_behavioral_reliability`, "
            "`evaluate`, or `run_evaluation`."
        )
        return

    data = as_plain(result)
    if not isinstance(data, dict):
        st.write(data)
        return

    metric_keys = [
        "rca_correct",
        "grounded",
        "investigation_sufficient",
        "tool_efficient",
        "behavioral_slo_pass",
    ]
    cols = st.columns(len(metric_keys))
    for col, key in zip(cols, metric_keys):
        value = data.get(key, "n/a")
        col.metric(key.replace("_", " ").title(), str(value))

    if "reasons" in data:
        st.subheader("Reasons")
        reasons = data["reasons"]
        if isinstance(reasons, list):
            for reason in reasons:
                st.write(f"- {reason}")
        else:
            st.write(reasons)

    with st.expander("Raw evaluator output"):
        st.json(data)


def render_trace_summary(trace: Any) -> None:
    render_tool_timeline(trace)
    st.markdown("**RCA**")
    st.write(trace_field(trace, "final_root_cause", "") or "No final RCA produced.")


def main() -> None:
    st.set_page_config(
        page_title="Reliable Incident Agent",
        layout="wide",
    )
    st.title("Reliable Incident Agent")
    st.caption("Local demo skeleton for autonomous incident investigation and behavioral evaluation.")

    incidents, incident_source = load_incidents()
    st.caption(incident_source)

    options = {incident_id(incident): incident for incident in incidents}
    selected_id = st.selectbox("Incident", list(options.keys()))
    selected_incident = options[selected_id]
    st.write(incident_description(selected_incident))

    if st.session_state.get("selected_incident_id") != selected_id:
        st.session_state.selected_incident_id = selected_id
        st.session_state.trace = make_trace(selected_incident)
        st.session_state.trace_source = "Initial placeholder trace."

    if st.button("Investigate", type="primary"):
        st.session_state.trace, st.session_state.trace_source = investigate(selected_incident)

    trace = st.session_state.trace
    st.caption(st.session_state.trace_source)

    left, right = st.columns([1, 1])
    with left:
        st.subheader("Tool Call Timeline")
        render_tool_timeline(trace)

    with right:
        st.subheader("RCA")
        final_root_cause = trace_field(trace, "final_root_cause", "")
        st.write(final_root_cause or "No final RCA produced yet.")

    st.divider()
    st.subheader("Behavioral Reliability")
    render_behavioral_reliability(trace)

    st.divider()
    st.subheader("Same Answer, Different Trajectory")
    st.caption("Weak mode intentionally jumps to the correct RCA from insufficient evidence; reliable mode gathers discriminating evidence.")
    if st.button("Compare Weak vs Reliable"):
        st.session_state.weak_trace, _ = investigate(selected_incident, mode="weak")
        st.session_state.reliable_trace, _ = investigate(selected_incident, mode="reliable")

    weak_trace = st.session_state.get("weak_trace")
    reliable_trace = st.session_state.get("reliable_trace")
    if weak_trace and reliable_trace:
        weak_col, reliable_col = st.columns(2)
        with weak_col:
            st.markdown("### Weak Agent")
            render_trace_summary(weak_trace)
            render_behavioral_reliability(weak_trace)
        with reliable_col:
            st.markdown("### Reliable Agent")
            render_trace_summary(reliable_trace)
            render_behavioral_reliability(reliable_trace)


if __name__ == "__main__":
    main()
