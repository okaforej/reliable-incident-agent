"""Reliable Incident Agent package."""

from .evaluator import evaluate_trace
from .investigator import run_investigation
from .models import (
    BehavioralEvaluation,
    ExpectedOutcome,
    InvestigationRequest,
    InvestigationResponse,
    InvestigationTrace,
    ToolCall,
)

__all__ = [
    "BehavioralEvaluation",
    "ExpectedOutcome",
    "InvestigationRequest",
    "InvestigationResponse",
    "InvestigationTrace",
    "ToolCall",
    "evaluate_trace",
    "run_investigation",
]
