"""FastAPI service for the Reliable Incident Agent."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .db import DB_PATH, init_db
from .evaluator import evaluate_trace
from .investigator import (
    confirm_rollback,
    continue_investigation_chat,
    default_provider,
    run_investigation,
)
from .models import (
    ActionConfirmationResponse,
    AgentMode,
    ChatMessageRequest,
    ChatMessageResponse,
    ComparisonRequest,
    ComparisonResponse,
    ComparisonSummary,
    HealthResponse,
    InvestigationAccepted,
    InvestigationEvent,
    InvestigationRequest,
    InvestigationResponse,
    InvestigationRunStatus,
    InvestigationSummary,
    ScenarioDetail,
    ScenarioSummary,
)
from .providers import ModelProvider
from .replay import ReplayRepository, internal_scenario_id, public_scenario_id

ProviderFactory = Callable[[], ModelProvider]
_provider_factory: ProviderFactory = default_provider

app = FastAPI(title="Reliable Incident Agent", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def set_model_provider_factory(factory: ProviderFactory) -> None:
    """Override provider creation for tests; production uses OpenAI env config."""

    global _provider_factory
    _provider_factory = factory


def _repo() -> ReplayRepository:
    if not DB_PATH.exists():
        init_db()
    return ReplayRepository()


def _provider() -> ModelProvider:
    return _provider_factory()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        openai_api_key_configured=bool(os.environ.get("OPENAI_API_KEY")),
        openai_model=os.environ.get("OPENAI_MODEL"),
    )


@app.get("/scenarios", response_model=list[ScenarioSummary])
def list_scenarios() -> list[ScenarioSummary]:
    return _repo().list_scenarios()


@app.get("/scenarios/{scenario_id}", response_model=ScenarioDetail)
def get_scenario(scenario_id: str) -> ScenarioDetail:
    try:
        return _repo().get_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_id}") from exc


@app.post(
    "/investigations",
    response_model=InvestigationAccepted,
    status_code=202,
)
def create_investigation(request: InvestigationRequest) -> InvestigationAccepted:
    repo = _repo()
    scenario_id = internal_scenario_id(request.scenario_id)
    try:
        repo.get_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {request.scenario_id}") from exc
    replay_instance_id = repo.create_replay_instance(scenario_id)
    run_id = repo.create_pending_run(scenario_id, replay_instance_id, request.mode)
    threading.Thread(
        target=_execute_pending_investigation,
        args=(run_id,),
        name=f"investigation-{run_id}",
        daemon=True,
    ).start()
    return InvestigationAccepted(
        run_id=run_id,
        scenario_id=public_scenario_id(scenario_id),
        status="queued",
    )


@app.get("/investigations", response_model=list[InvestigationSummary])
def list_investigations() -> list[InvestigationSummary]:
    return _repo().list_investigations()


@app.get("/investigations/{run_id}", response_model=InvestigationRunStatus)
def get_investigation(run_id: str) -> InvestigationRunStatus:
    try:
        return _repo().get_run_status(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown investigation: {run_id}") from exc


@app.get(
    "/investigations/{run_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                }
            }
        }
    },
)
def get_investigation_events(
    run_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    repo = _repo()
    try:
        repo.get_run_status(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown investigation: {run_id}") from exc
    last_event_id = request.headers.get("last-event-id")
    if last_event_id:
        try:
            after = max(after, int(last_event_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer.") from exc
    return StreamingResponse(
        _stream_events(run_id, after),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/investigations/{run_id}/evaluation")
def get_investigation_evaluation(run_id: str) -> dict[str, object]:
    try:
        repo = _repo()
        _require_completed(repo, run_id)
        return {"run_id": run_id, "evaluation": repo.get_evaluation(run_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown investigation: {run_id}") from exc


@app.post("/investigations/{run_id}/messages", response_model=ChatMessageResponse)
def post_message(run_id: str, request: ChatMessageRequest) -> ChatMessageResponse:
    repo = _repo()
    try:
        _require_completed(repo, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown investigation: {run_id}") from exc
    try:
        return continue_investigation_chat(run_id, request.message, repo, _provider())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _provider_unavailable(exc) from exc


@app.post(
    "/investigations/{run_id}/actions/{proposal_id}/confirm",
    response_model=ActionConfirmationResponse,
)
def confirm_action(run_id: str, proposal_id: str) -> ActionConfirmationResponse:
    try:
        repo = _repo()
        _require_completed(repo, run_id)
        return confirm_rollback(run_id, proposal_id, repo, provider_factory=_provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown action proposal: {proposal_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/comparisons", response_model=ComparisonResponse)
def create_comparison(request: ComparisonRequest) -> ComparisonResponse:
    repo = _repo()
    scenario_id = internal_scenario_id(request.scenario_id)
    baseline = _create_investigation_with_repo(repo, scenario_id, "baseline")
    candidate = _create_investigation_with_repo(repo, scenario_id, "candidate")
    comparison_id = repo.persist_comparison(scenario_id, baseline, candidate)
    return ComparisonResponse(
        comparison_id=comparison_id,
        scenario_id=public_scenario_id(scenario_id),
        baseline=baseline,
        candidate=candidate,
    )


@app.get("/comparisons", response_model=list[ComparisonSummary])
def list_comparisons() -> list[ComparisonSummary]:
    return _repo().list_comparisons()


@app.get("/comparisons/{comparison_id}", response_model=ComparisonResponse)
def get_comparison(comparison_id: str) -> ComparisonResponse:
    try:
        return _repo().get_comparison(comparison_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown comparison: {comparison_id}") from exc


def _create_investigation_with_repo(
    repo: ReplayRepository,
    scenario_id: str,
    mode: AgentMode,
) -> InvestigationResponse:
    try:
        repo.get_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_id}") from exc
    replay_instance_id = repo.create_replay_instance(scenario_id)
    try:
        trace = run_investigation(
            scenario_id,
            mode,
            repo,
            _provider(),
            replay_instance_id,
        )
    except Exception as exc:
        raise _provider_unavailable(exc) from exc
    expected = repo.get_expected_outcome(scenario_id)
    evaluation = evaluate_trace(trace, expected)
    run_id = repo.persist_run(scenario_id, replay_instance_id, trace, evaluation)
    try:
        if trace.final_result.action_proposal:
            repo.persist_action_proposal(run_id, trace.final_result.action_proposal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return InvestigationResponse(run_id=run_id, trace=trace, evaluation=evaluation)


def _execute_pending_investigation(run_id: str) -> None:
    """Run one claimed investigation in an isolated worker connection."""

    repo = _repo()
    try:
        scope = repo.get_run_scope(run_id)
        incident = repo.get_agent_context(scope["scenario_id"])
        started_payload = {
            "scenario_id": public_scenario_id(scope["scenario_id"]),
            "incident_id": incident["id"],
            "agent_config_id": _run_agent_mode(repo, run_id),
        }
        if not repo.claim_run(run_id, started_payload):
            return
        trace = run_investigation(
            scope["scenario_id"],
            started_payload["agent_config_id"],
            repo,
            _provider(),
            scope["replay_instance_id"],
            progress_callback=lambda event_type, summary, payload: repo.append_event(
                run_id,
                event_type,
                summary,
                payload,
            ),
        )
        if trace.final_result.outcome == "error":
            detail = trace.final_result.missing_evidence[0] if trace.final_result.missing_evidence else (
                "Investigation failed before producing a defensible result."
            )
            raise RuntimeError(detail)
        # Evaluator-only truth is intentionally loaded only after the trace exists.
        expected = repo.get_expected_outcome(scope["scenario_id"])
        evaluation = evaluate_trace(trace, expected)
        repo.complete_run(run_id, trace, evaluation)
    except Exception as exc:  # noqa: BLE001 - worker must terminate durably
        repo.fail_run(run_id, _safe_error_detail(exc))


def _run_agent_mode(repo: ReplayRepository, run_id: str) -> AgentMode:
    value = repo.get_run_metadata(run_id)["agent_config_id"]
    if value not in ("baseline", "candidate"):
        raise ValueError("Investigation has an invalid agent configuration.")
    return value


def _require_completed(repo: ReplayRepository, run_id: str) -> None:
    status = repo.get_run_status(run_id)
    if status.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Investigation is {status.status}; wait for completion.",
        )


def _stream_events(run_id: str, after: int):
    repo = _repo()
    cursor = after
    heartbeat_at = time.monotonic()
    yield "retry: 1000\n\n"
    while True:
        events = repo.list_events(run_id, cursor)
        for event in events:
            cursor = event.id
            yield _sse_frame(event)
        status = repo.get_run_status(run_id).status
        if status in ("completed", "failed"):
            return
        now = time.monotonic()
        if now - heartbeat_at >= 15:
            yield ": keep-alive\n\n"
            heartbeat_at = now
        time.sleep(0.1)


def _sse_frame(event: InvestigationEvent) -> str:
    return (
        f"id: {event.id}\n"
        f"event: {event.type}\n"
        f"data: {event.model_dump_json()}\n\n"
    )


def _provider_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"Model provider unavailable: {_safe_error_detail(exc)}")


def _safe_error_detail(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError) or isinstance(exc.__cause__, json.JSONDecodeError):
        return "provider returned malformed JSON"
    text = str(exc) or exc.__class__.__name__
    redacted = text
    for name, value in os.environ.items():
        if ("KEY" in name or "TOKEN" in name or "SECRET" in name) and value:
            redacted = redacted.replace(value, "[redacted]")
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        redacted = redacted.replace(openai_key, "[redacted]")
    if len(redacted) > 240:
        redacted = redacted[:237] + "..."
    return redacted
