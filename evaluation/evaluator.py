"""Deterministic behavioral SLIs over observable investigation trajectories."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from shared.models import InvestigationTrace, ToolCall

_KNOWN_TOOLS = {
    "get_dependencies",
    "get_metrics",
    "get_recent_changes",
    "get_service_health",
    "search_logs",
}
_EVIDENCE_CONCEPTS = {
    "postgres": {"postgres", "database", "db"},
    "payments": {"payments", "payment"},
    "connection_exhaustion": {
        "active connections",
        "connection exhaustion",
        "connection pool exhausted",
        "connections active",
        "max connections",
        "pool exhaustion",
        "pool saturation",
        "db timeout",
        "db_timeout",
    },
    "configuration_change": {
        "configuration change",
        "config change",
        "pool configuration",
        "pool config",
        "database pool",
        "db pool",
        "db_pool",
        "max_open_connections",
        "deployment",
        "deploy",
    },
    "dependency_failure": {
        "dependency failure",
        "dependency failures",
        "upstream failure",
        "upstream failures",
    },
}


@dataclass(frozen=True)
class BehavioralEvaluation:
    rca_correct: bool
    grounded: bool
    investigation_sufficient: bool
    tool_efficient: bool
    behavioral_slo_pass: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_trace(trace: InvestigationTrace) -> BehavioralEvaluation:
    """Evaluate answer correctness and observable trajectory invariants.

    These checks do not inspect or claim to score hidden chain-of-thought.
    "Grounded" means the retrieved tool results visibly support concepts in the
    final RCA, while sufficiency and efficiency inspect evidence diversity and
    call behavior.
    """

    reasons: list[str] = []
    rca_correct = _equivalent_root_cause(
        trace.final_root_cause, trace.expected_root_cause
    )
    reasons.append(
        "Final RCA matches the expected root cause."
        if rca_correct
        else "Final RCA does not match the expected root cause."
    )

    supported, claimed = _supported_concepts(trace)
    grounded = bool(claimed) and supported == claimed
    if grounded:
        reasons.append(
            "Retrieved evidence supports every recognized causal concept in the RCA."
        )
    elif not claimed:
        reasons.append("RCA contains no recognized causal concept to verify.")
    else:
        missing = ", ".join(sorted(claimed - supported))
        reasons.append(f"Retrieved evidence does not support: {missing}.")

    informative_tools = {
        call.tool_name for call in trace.tool_calls if _is_informative(call)
    }
    evidence_families = {
        _tool_family(name) for name in informative_tools if _tool_family(name)
    }
    investigation_sufficient = (
        bool(supported)
        and len(informative_tools) >= 3
        and len(evidence_families) >= 2
    )
    reasons.append(
        "Investigation used at least three informative tools across two evidence families."
        if investigation_sufficient
        else "Investigation lacks enough independent, informative evidence to distinguish alternatives."
    )

    efficiency_issues = _efficiency_issues(trace.tool_calls)
    tool_efficient = not efficiency_issues
    reasons.append(
        "Tool trajectory stayed within budget with no duplicate or irrelevant calls."
        if tool_efficient
        else "Tool efficiency failed: " + "; ".join(efficiency_issues) + "."
    )

    behavioral_slo_pass = grounded and investigation_sufficient and tool_efficient
    return BehavioralEvaluation(
        rca_correct=rca_correct,
        grounded=grounded,
        investigation_sufficient=investigation_sufficient,
        tool_efficient=tool_efficient,
        behavioral_slo_pass=behavioral_slo_pass,
        reasons=reasons,
    )


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _concepts(text: str) -> set[str]:
    normalized = _normalize(text)
    return {
        concept
        for concept, aliases in _EVIDENCE_CONCEPTS.items()
        if any(_normalize(alias) in normalized for alias in aliases)
    }


def _equivalent_root_cause(actual: str, expected: str) -> bool:
    actual_normalized = _normalize(actual)
    expected_normalized = _normalize(expected)
    if not actual_normalized or not expected_normalized:
        return False
    if actual_normalized == expected_normalized:
        return True
    expected_concepts = _concepts(expected)
    return bool(expected_concepts) and expected_concepts <= _concepts(actual)


def _flatten(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _supported_concepts(
    trace: InvestigationTrace,
) -> tuple[set[str], set[str]]:
    claimed = _concepts(trace.final_root_cause)
    evidence_text = " ".join(_flatten(call.result) for call in trace.tool_calls)
    return claimed & _concepts(evidence_text), claimed


def _is_informative(call: ToolCall) -> bool:
    result = call.result
    if call.tool_name == "search_logs":
        return bool(result.get("matches"))
    if call.tool_name == "get_recent_changes":
        return bool(result.get("changes"))
    if call.tool_name == "get_dependencies":
        return bool(result.get("dependencies"))
    if call.tool_name == "get_metrics":
        return bool(result.get("metrics"))
    if call.tool_name == "get_service_health":
        return result.get("status") not in {None, "unknown"}
    return False


def _tool_family(tool_name: str) -> str | None:
    if tool_name in {"get_metrics", "get_service_health", "search_logs"}:
        return "runtime_signal"
    if tool_name == "get_recent_changes":
        return "change_event"
    if tool_name == "get_dependencies":
        return "topology"
    return None


def _efficiency_issues(tool_calls: Iterable[ToolCall]) -> list[str]:
    calls = list(tool_calls)
    issues: list[str] = []
    if len(calls) > 6:
        issues.append(f"{len(calls)} calls exceeds the six-call budget")

    signatures = [
        (call.tool_name, json.dumps(call.arguments, sort_keys=True, default=str))
        for call in calls
    ]
    if len(signatures) != len(set(signatures)):
        issues.append("exact duplicate calls detected")

    unknown = sorted({call.tool_name for call in calls} - _KNOWN_TOOLS)
    if unknown:
        issues.append("unknown tools: " + ", ".join(unknown))
    if any(call.result.get("relevant") is False for call in calls):
        issues.append("explicitly irrelevant calls detected")
    return issues