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
TOOL_CALL_BUDGET = 8


def evaluate_trace(trace: InvestigationTrace, expected: ExpectedOutcome) -> BehavioralEvaluation:
    reasons: list[str] = []
    inconclusive_expected = _is_inconclusive(expected.root_cause)
    inconclusive_actual = trace.final_result.outcome == "abstain" or _is_inconclusive(trace.final_root_cause)
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
        _has_inconclusive_grounding(trace) and _final_evidence_was_retrieved(trace)
        if inconclusive_actual
        else bool(claimed) and claimed <= supported and _final_evidence_was_retrieved(trace)
    )
    reasons.append(
        "Observed evidence supports claimed concepts: " + ", ".join(sorted(claimed)) + "."
        if grounded
        else "Observed evidence is missing support for claimed concepts: "
        + ", ".join(sorted(claimed - supported))
        + "."
    )

    informative_calls = [call for call in trace.tool_calls if _informative(call)]
    families = _evidence_families(trace.tool_calls)
    investigation_sufficient = (
        len(families) >= 2 and len(informative_calls) >= 3
        if inconclusive_actual
        else len(families) >= 3
        and len(informative_calls) >= 4
        and _distinguishes_plausible_alternatives(trace, claimed)
    )
    if investigation_sufficient and inconclusive_actual:
        reasons.append("Investigation gathered enough evidence to justify an inconclusive RCA.")
    elif investigation_sufficient:
        reasons.append(
            "Investigation gathered evidence families: "
            + ", ".join(sorted(families))
            + "."
        )
    else:
        reasons.append("Investigation lacks enough independent evidence to distinguish alternatives.")

    efficiency_issues = _efficiency_issues(trace)
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
    cited = set(trace.final_result.evidence_ids)
    evidence_text = " ".join(
        _flatten(record)
        for call in trace.tool_calls
        if call.status == "ok"
        for record in _matching_evidence_records(call.result, cited)
    )
    return _concepts(evidence_text)


def _final_evidence_was_retrieved(trace: InvestigationTrace) -> bool:
    retrieved = {
        evidence_id
        for call in trace.tool_calls
        if call.status == "ok"
        for evidence_id in call.evidence_ids
    }
    return bool(trace.final_result.evidence_ids) and set(trace.final_result.evidence_ids) <= retrieved


def _matching_evidence_records(value: Any, cited: set[str]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        identifier = next(
            (
                value[key]
                for key in ("id", "evidence_id")
                if isinstance(value.get(key), str)
            ),
            None,
        )
        if identifier in cited:
            return [value]
        for child in value.values():
            matches.extend(_matching_evidence_records(child, cited))
    elif isinstance(value, list):
        for child in value:
            matches.extend(_matching_evidence_records(child, cited))
    return matches


def _has_inconclusive_grounding(trace: InvestigationTrace) -> bool:
    missing_text = _normalize(" ".join(trace.final_result.missing_evidence))
    if not missing_text:
        return False
    cited = set(trace.final_result.evidence_ids)
    return any(
        call.status == "ok"
        and _is_relevant_negative_evidence(call, missing_text)
        and bool(cited & set(call.evidence_ids))
        for call in trace.tool_calls
    )


def _is_relevant_negative_evidence(call: ToolCall, missing_text: str) -> bool:
    service = call.arguments.get("service")
    if not isinstance(service, str) or service not in missing_text:
        return False

    result = call.result
    if call.tool_name == "get_recent_changes":
        return "change" in missing_text and result.get("changes") == []
    if call.tool_name == "search_logs":
        return ("log" in missing_text or "event" in missing_text) and result.get("matches") == []
    if call.tool_name == "get_metrics":
        return "metric" in missing_text and result.get("metrics") == []
    if call.tool_name == "get_dependencies":
        return ("dependency" in missing_text or "topology" in missing_text) and result.get("dependencies") == []
    return False


def _distinguishes_plausible_alternatives(
    trace: InvestigationTrace,
    claimed_concepts: set[str],
) -> bool:
    evidence_text = " ".join(
        _flatten(call.result) for call in trace.tool_calls if call.status == "ok"
    ).lower()
    services = {
        service
        for call in trace.tool_calls
        if call.status == "ok"
        and _informative(call)
        if isinstance((service := call.arguments.get("service")), str)
    }

    if {"checkout", "postgres", "connection_exhaustion", "db_pool_change"} <= claimed_concepts:
        return (
            "checkout" in services
            and "postgres" in services
            and "payments" in services
        )

    if {"payments", "gateway_timeout", "timeout_change"} <= claimed_concepts:
        return (
            "checkout" in services
            and "payments" in services
            and ("postgres" in services or "postgres" in evidence_text)
        )

    return True


def _informative(call: ToolCall) -> bool:
    if call.status != "ok":
        return False
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
        return result.get("status") not in {None, "unknown"}
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


def _efficiency_issues(trace: InvestigationTrace) -> list[str]:
    calls = trace.tool_calls
    issues: list[str] = []
    if len(calls) > TOOL_CALL_BUDGET:
        issues.append(
            f"{len(calls)} calls exceeds the {TOOL_CALL_BUDGET}-call budget"
        )
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
    relevant_text = _normalize(trace.final_root_cause) + " " + " ".join(
        _normalize(_flatten(call.result))
        for call in calls
        if call.tool_name == "get_dependencies"
    )
    irrelevant = sorted(
        {
            service
            for call in calls
            if call.tool_name in known
            and isinstance((service := call.arguments.get("service")), str)
            and _normalize(service) not in relevant_text
        }
    )
    if irrelevant:
        issues.append("irrelevant service queries: " + ", ".join(irrelevant))
    return issues
