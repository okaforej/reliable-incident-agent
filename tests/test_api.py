from __future__ import annotations

from conftest import EXPECTED_RCA, SCENARIO_ID, import_module
from fastapi.testclient import TestClient


def test_comparison_endpoint_returns_weak_and_reliable_traces_and_evaluations() -> None:
    api = import_module("api")
    assert hasattr(api, "app"), "Expected reliable_incident_agent.api.app to be a FastAPI app."

    response = TestClient(api.app).get(f"/comparisons/{SCENARIO_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario_id"] == SCENARIO_ID

    weak = payload["weak"]
    reliable = payload["reliable"]

    assert weak["trace"]["final_root_cause"] == EXPECTED_RCA
    assert reliable["trace"]["final_root_cause"] == EXPECTED_RCA

    assert weak["evaluation"]["rca_correct"] is True
    assert weak["evaluation"]["behavioral_slo_pass"] is False
    assert reliable["evaluation"]["rca_correct"] is True
    assert reliable["evaluation"]["behavioral_slo_pass"] is True


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
