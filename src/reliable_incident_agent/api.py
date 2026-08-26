"""FastAPI service for the Reliable Incident Agent."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import DB_PATH, init_db
from .evaluator import evaluate_trace
from .investigator import run_investigation
from .models import (
    ComparisonResponse,
    InvestigationRequest,
    InvestigationResponse,
    ScenarioDetail,
    ScenarioEvidence,
    ScenarioSummary,
)
from .replay import ReplayRepository

app = FastAPI(title="Reliable Incident Agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _repo() -> ReplayRepository:
    if not DB_PATH.exists():
        init_db()
    return ReplayRepository()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/scenarios", response_model=list[ScenarioSummary])
def list_scenarios() -> list[ScenarioSummary]:
    return _repo().list_scenarios()


@app.get("/scenarios/{scenario_id}", response_model=ScenarioDetail)
def get_scenario(scenario_id: str) -> ScenarioDetail:
    return _repo().get_scenario(scenario_id)


@app.get("/scenarios/{scenario_id}/evidence", response_model=ScenarioEvidence)
def get_evidence(scenario_id: str) -> ScenarioEvidence:
    return _repo().get_evidence(scenario_id)


@app.post("/investigations", response_model=InvestigationResponse)
def create_investigation(request: InvestigationRequest) -> InvestigationResponse:
    repo = _repo()
    trace = run_investigation(request.scenario_id, request.mode, repo)
    expected = repo.get_expected_outcome(request.scenario_id)
    evaluation = evaluate_trace(trace, expected)
    run_id = repo.persist_run(request.scenario_id, request.mode, trace, evaluation)
    return InvestigationResponse(run_id=run_id, trace=trace, evaluation=evaluation)


@app.get("/investigations/{run_id}")
def get_investigation(run_id: str) -> dict[str, object]:
    return {"run_id": run_id, "trace": _repo().get_run(run_id)}


@app.get("/investigations/{run_id}/evaluation")
def get_investigation_evaluation(run_id: str) -> dict[str, object]:
    return {"run_id": run_id, "evaluation": _repo().get_evaluation(run_id)}


@app.get("/comparisons/{scenario_id}", response_model=ComparisonResponse)
def compare(scenario_id: str) -> ComparisonResponse:
    baseline = create_investigation(
        InvestigationRequest(scenario_id=scenario_id, mode="baseline")
    )
    candidate = create_investigation(
        InvestigationRequest(scenario_id=scenario_id, mode="candidate")
    )
    return ComparisonResponse(
        scenario_id=scenario_id,
        baseline=baseline,
        candidate=candidate,
    )
