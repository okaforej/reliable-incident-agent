from __future__ import annotations

from conftest import EXPECTED_RCA, SCENARIO_ID, import_module
from fastapi.testclient import TestClient


def test_comparison_endpoint_returns_baseline_and_candidate_traces_and_evaluations() -> None:
    api = import_module("api")
    assert hasattr(api, "app"), "Expected reliable_incident_agent.api.app to be a FastAPI app."

    response = TestClient(api.app).get(f"/comparisons/{SCENARIO_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario_id"] == SCENARIO_ID

    baseline = payload["baseline"]
    candidate = payload["candidate"]

    assert baseline["trace"]["final_root_cause"] == EXPECTED_RCA
    assert candidate["trace"]["final_root_cause"] == EXPECTED_RCA

    assert baseline["evaluation"]["rca_correct"] is True
    assert baseline["evaluation"]["grounded"] is True
    assert baseline["evaluation"]["investigation_sufficient"] is True
    assert baseline["evaluation"]["tool_efficient"] is True
    assert baseline["evaluation"]["behavioral_slo_pass"] is True

    assert candidate["evaluation"]["rca_correct"] is True
    assert candidate["evaluation"]["grounded"] is False
    assert candidate["evaluation"]["investigation_sufficient"] is False
    assert candidate["evaluation"]["tool_efficient"] is True
    assert candidate["evaluation"]["behavioral_slo_pass"] is False


def test_persisted_investigation_round_trip_preserves_tool_calls() -> None:
    api = import_module("api")
    client = TestClient(api.app)
    created = client.post(
        "/investigations",
        json={"scenario_id": SCENARIO_ID, "mode": "baseline"},
    )

    assert created.status_code == 200
    run_id = created.json()["run_id"]
    fetched = client.get(f"/investigations/{run_id}")

    assert fetched.status_code == 200
    trace = fetched.json()["trace"]
    first_call = trace["tool_calls"][0]
    assert first_call["tool_name"] == "get_service_health"
    assert first_call["arguments"] == {"service": "checkout"}
    assert first_call["result"]["service"] == "checkout"


def test_scenarios_endpoint_lists_three_replay_scenarios() -> None:
    api = import_module("api")
    response = TestClient(api.app).get("/scenarios")

    assert response.status_code == 200
    scenario_ids = {scenario["id"] for scenario in response.json()}
    assert {
        "checkout_db_pool_exhaustion",
        "payments_gateway_timeout",
        "insufficient_frontend_evidence",
    } <= scenario_ids
