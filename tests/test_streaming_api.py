from __future__ import annotations

import json
import threading
import time
from typing import Any

from conftest import checkout_provider, recovery_provider
from fastapi.testclient import TestClient

PUBLIC_SCENARIO_ID = "checkout_latency_spike"


def _wait_for_terminal(client: TestClient, run_id: str, timeout: float = 3) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(f"/investigations/{run_id}").json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"Investigation {run_id} did not terminate")


def _start(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/investigations",
        json={"scenario_id": PUBLIC_SCENARIO_ID, "mode": "candidate"},
    )
    assert response.status_code == 202
    return response.json()


def _sse_events(body: str) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


class _BlockingProvider:
    provider_name = "blocking-fake"
    model = "fake-tool-model"

    def __init__(self) -> None:
        self.delegate = checkout_provider()
        self.started = threading.Event()
        self.release = threading.Event()

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self.delegate.requests

    def respond(self, **kwargs: Any) -> Any:
        self.started.set()
        if not self.release.wait(timeout=3):
            raise RuntimeError("test provider timed out")
        return self.delegate.respond(**kwargs)


class _ExplodingProvider:
    provider_name = "exploding"
    model = "fake-tool-model"

    def __init__(self, secret: str) -> None:
        self.secret = secret

    def respond(self, **_kwargs: Any) -> Any:
        raise RuntimeError(f"provider rejected request containing {self.secret}")


def test_start_is_accepted_before_provider_completion_and_pending_gets_are_read_only() -> None:
    from reliable_incident_agent import api

    provider = _BlockingProvider()
    api.set_model_provider_factory(lambda: provider)
    client = TestClient(api.app)

    started_at = time.monotonic()
    accepted = _start(client)
    elapsed = time.monotonic() - started_at
    try:
        assert elapsed < 0.5
        assert accepted == {
            "run_id": accepted["run_id"],
            "scenario_id": PUBLIC_SCENARIO_ID,
            "status": "queued",
        }
        assert provider.started.wait(timeout=1)

        pending = client.get(f"/investigations/{accepted['run_id']}")
        assert pending.status_code == 200
        assert pending.json() == {
            "run_id": accepted["run_id"],
            "scenario_id": PUBLIC_SCENARIO_ID,
            "status": "running",
            "response": None,
            "error": None,
            "follow_ups": [],
            "action_result": None,
        }
        assert len(provider.requests) == 0
        assert client.post(
            f"/investigations/{accepted['run_id']}/messages",
            json={"message": "What is happening?"},
        ).status_code == 409
        assert client.post(
            f"/investigations/{accepted['run_id']}/actions/not-ready/confirm"
        ).status_code == 409
    finally:
        provider.release.set()

    assert _wait_for_terminal(client, accepted["run_id"])["status"] == "completed"


def test_events_are_durable_ordered_typed_and_completion_is_canonical() -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    provider = checkout_provider()
    api.set_model_provider_factory(lambda: provider)
    client = TestClient(api.app)
    accepted = _start(client)
    terminal = _wait_for_terminal(client, accepted["run_id"])

    assert terminal["status"] == "completed"
    assert terminal["error"] is None
    canonical = terminal["response"]
    assert canonical["run_id"] == accepted["run_id"]
    assert canonical["trace"]["provider_metadata"]["provider"] == "fake"

    events = ReplayRepository().list_events(accepted["run_id"])
    assert [event.id for event in events] == list(range(1, len(events) + 1))
    assert events[0].type == "investigation.started"
    assert events[0].payload.scenario_id == PUBLIC_SCENARIO_ID
    assert events[0].payload.incident_id == "inc_checkout_001"
    assert events[-2].type == "hypotheses.updated"
    assert events[-1].type == "investigation.completed"
    assert events[-1].payload.tool_call_count == len(canonical["trace"]["tool_calls"])
    assert [event.type for event in events].count("tool.started") == 6
    assert [event.type for event in events].count("tool.completed") == 6

    streamed = client.get(f"/investigations/{accepted['run_id']}/events")
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert set(
        api.app.openapi()["paths"]["/investigations/{run_id}/events"]["get"]["responses"][
            "200"
        ]["content"]
    ) == {"text/event-stream"}
    frames = _sse_events(streamed.text)
    assert [frame["id"] for frame in frames] == list(range(1, len(frames) + 1))
    assert frames[-1]["type"] == "investigation.completed"


def test_sse_reconnect_replays_only_missed_events_without_duplicate_execution() -> None:
    from reliable_incident_agent import api

    provider = checkout_provider()
    api.set_model_provider_factory(lambda: provider)
    client = TestClient(api.app)
    accepted = _start(client)
    _wait_for_terminal(client, accepted["run_id"])
    request_count = len(provider.requests)

    all_events = _sse_events(
        client.get(f"/investigations/{accepted['run_id']}/events").text
    )
    cursor = all_events[3]["id"]
    query_replay = _sse_events(
        client.get(
            f"/investigations/{accepted['run_id']}/events",
            params={"after": cursor},
        ).text
    )
    header_replay = _sse_events(
        client.get(
            f"/investigations/{accepted['run_id']}/events",
            headers={"Last-Event-ID": str(cursor)},
        ).text
    )

    assert query_replay == header_replay
    assert query_replay
    assert all(frame["id"] > cursor for frame in query_replay)
    assert len(provider.requests) == request_count
    assert client.get(f"/investigations/{accepted['run_id']}").json()["status"] == "completed"


def test_provider_failure_persists_one_sanitized_terminal_event(monkeypatch: Any) -> None:
    from reliable_incident_agent import api
    from reliable_incident_agent.replay import ReplayRepository

    secret = "sk-streaming-secret"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    api.set_model_provider_factory(lambda: _ExplodingProvider(secret))
    client = TestClient(api.app)
    accepted = _start(client)
    terminal = _wait_for_terminal(client, accepted["run_id"])

    assert terminal["status"] == "failed"
    assert terminal["response"] is None
    assert "provider rejected request" in terminal["error"]
    assert secret not in terminal["error"]
    events = ReplayRepository().list_events(accepted["run_id"])
    assert [event.type for event in events] == [
        "investigation.started",
        "investigation.failed",
    ]
    assert events[-1].payload.error == terminal["error"]

    api._execute_pending_investigation(accepted["run_id"])
    unchanged = ReplayRepository().list_events(accepted["run_id"])
    assert [event.type for event in unchanged].count("investigation.failed") == 1


def test_async_action_proposal_is_confirmable_after_completed_event() -> None:
    from reliable_incident_agent import api

    providers = [checkout_provider(action=True), recovery_provider()]
    api.set_model_provider_factory(lambda: providers.pop(0))
    client = TestClient(api.app)
    accepted = _start(client)
    terminal = _wait_for_terminal(client, accepted["run_id"])
    proposal = terminal["response"]["trace"]["final_result"]["action_proposal"]

    streamed = _sse_events(
        client.get(f"/investigations/{accepted['run_id']}/events").text
    )
    assert streamed[-1]["type"] == "investigation.completed"
    confirmed = client.post(
        f"/investigations/{accepted['run_id']}/actions/{proposal['id']}/confirm"
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["verification_status"] == "verified"
