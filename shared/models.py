"""Minimal shared trajectory contract.

Both the runtime investigator and behavioral evaluator should use these models.
Keep this file intentionally small so Codex and Copilot can coordinate without
creating competing schemas.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolCall:
    sequence: int
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InvestigationTrace:
    incident_id: str
    incident_description: str
    expected_root_cause: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_root_cause: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "incident_description": self.incident_description,
            "expected_root_cause": self.expected_root_cause,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "final_root_cause": self.final_root_cause,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InvestigationTrace":
        return cls(
            incident_id=data["incident_id"],
            incident_description=data["incident_description"],
            expected_root_cause=data["expected_root_cause"],
            tool_calls=[ToolCall(**call) for call in data.get("tool_calls", [])],
            final_root_cause=data.get("final_root_cause", ""),
        )
