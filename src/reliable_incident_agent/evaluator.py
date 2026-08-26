"""Deterministic behavioral SLIs over observed investigation traces."""

from __future__ import annotations

import json
import re
from typing import Any

from .models import BehavioralEvaluation, ExpectedOutcome, InvestigationTrace, ToolCall

CONCEPTS = {
    "checkout": {"checkout"},
    "postgres": {"postgres", "database", "db"},
    "payments": {"payments", "payment"},
    "gateway_timeout": {"gateway timeout", "gateway timeouts", "external gateway", "504"},
    "connection_exhaustion": {
        "connection exhaustion",
        "connections",
        "max_connections",
        "too many clients",
        "connection slots",
        "db acquire timeout",
    },
    "db_pool_change": {
        "max_open_connections",
        "configuration",
        "config",
        "database pool",
    },
    "timeout_change": {"timeout_ms", "timeout to 500", "500 ms", "500ms", "lowered"},
}


def evaluate_trace(trace: InvestigationTrace, expected: ExpectedOutcome) -> BehavioralEvaluation:
    reasons: list[str] = []
    inconclusive_expected = _is_inconclusive(expected.root_cause)
    inconclusive_actual = _is_inconclusive(trace.final_root_cause)
    rca_correct = (
        inconclusive_actual if inconclusive_expected else _equivalent_root_cause(trace.final_root_cause, expected.root_cause)
    )
    reasons.append(
        "Final RCA matches expected root cause."
        if rca_correct
        else "Final RCA does not match expected root cause."
    )

    claimed = _concepts(trace.final_root_cause)
    supported = _supported_concepts(trace)
    grounded = (
        _has_inconclusive_grounding(trace)
        if inconclusive_actual
        else bool(claimed) and claimed <= supported
    )
    reasons.append(
        "Observed tool results support the causal concepts in the RCA."
        if grounded
        else "Observed tool results do not support every causal concept in the RCA."
    )

    families = _evidence_families(trace.tool_calls)
    investigation_sufficient = (
        len(families) >= 2 and len([call for call in trace.tool_calls if _informative(call)]) >= 3
        if inconclusive_actual
        else _has_tool(trace, "get_dependencies")
        and _has_tool(trace, "get_metrics")
        and _has_tool(trace, "get_recent_changes")
        and len(families) >= 3
    )
    if investigation_sufficient and inconclusive_actual:
        reasons.append("Investigation gathered enough evidence to justify an inconclusive RCA.")
    elif investigation_sufficient:
        reasons.append("Investigation gathered topology, runtime signal, and change evidence.")
    else:
        reasons.append("Investigation lacks enough independent evidence to distinguish alternatives.")

    efficiency_issues = _efficiency_issues(trace.tool_calls)
    tool_efficient = not efficiency_issues
    reasons.append(
        "Tool trajectory stayed focused and non-duplicative."
        if tool_efficient
        else "Tool efficiency failed: " + "; ".join(efficiency_issues) + "."
    )

    return BehavioralEvaluation(
        rca_correct=rca_correct,
        grounded=grounded,
        investigation_sufficient=investigation_sufficient,
        tool_efficient=tool_efficient,
        behavioral_slo_pass=grounded and investigation_sufficient and tool_efficient,
        reasons=reasons,
    )


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9_]+", text.lower()))


def _concepts(text: str) -> set[str]:
    normalized = _normalize(text)
    return {
        concept
        for concept, aliases in CONCEPTS.items()
        if any(_normalize(alias) in normalized for alias in aliases)
    }


def _equivalent_root_cause(actual: str, expected: str) -> bool:
    actual_concepts = _concepts(actual)
    expected_concepts = _concepts(expected)
    return bool(expected_concepts) and expected_concepts <= actual_concepts


def _is_inconclusive(text: str) -> bool:
    normalized = _normalize(text)
    return "insufficient evidence" in normalized or "inconclusive" in normalized


def _flatten(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _supported_concepts(trace: InvestigationTrace) -> set[str]:
    evidence_text = " ".join(_flatten(call.result) for call in trace.tool_calls)
    return _concepts(evidence_text)


def _has_inconclusive_grounding(trace: InvestigationTrace) -> bool:
    text = " ".join(_flatten(call.result) for call in trace.tool_calls).lower()
    return bool(trace.tool_calls) and (
        "insufficient" in text or "no matching" in text or "count\": 0" in text or "[]" in text
    )


def _has_tool(trace: InvestigationTrace, tool_name: str) -> bool:
    return any(call.tool_name == tool_name and _informative(call) for call in trace.tool_calls)


def _informative(call: ToolCall) -> bool:
    result = call.result
    if call.tool_name == "search_logs":
        return bool(result.get("matches") or result.get("events"))
    if call.tool_name == "get_metrics":
        return bool(result.get("metrics") or result.get("points"))
    if call.tool_name == "get_dependencies":
        return bool(result.get("dependencies"))
    if call.tool_name == "get_recent_changes":
        return bool(result.get("changes"))
    if call.tool_name == "get_service_health":
        return result.get("status") not in {None, "unknown", "healthy"}
    return False


def _evidence_families(calls: list[ToolCall]) -> set[str]:
    families: set[str] = set()
    for call in calls:
        if not _informative(call):
            continue
        if call.tool_name in {"get_service_health", "get_metrics", "search_logs"}:
            families.add("runtime_signal")
        elif call.tool_name == "get_dependencies":
            families.add("topology")
        elif call.tool_name == "get_recent_changes":
            families.add("change")
    return families


def _efficiency_issues(calls: list[ToolCall]) -> list[str]:
    issues: list[str] = []
    if len(calls) > 8:
        issues.append(f"{len(calls)} calls exceeds the eight-call budget")
    signatures = [
        (call.tool_name, json.dumps(call.arguments, sort_keys=True, default=str))
        for call in calls
    ]
    if len(signatures) != len(set(signatures)):
        issues.append("duplicate tool calls detected")
    known = {
        "get_service_health",
        "search_logs",
        "get_metrics",
        "get_recent_changes",
        "get_dependencies",
    }
    unknown = sorted({call.tool_name for call in calls} - known)
    if unknown:
        issues.append("unknown tools: " + ", ".join(unknown))
    return issues
