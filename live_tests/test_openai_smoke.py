from __future__ import annotations

import os

import pytest


@pytest.mark.live
def test_live_openai_investigator_smoke() -> None:
    if os.environ.get("RUN_LIVE_SMOKE") != "1":
        pytest.skip("Set RUN_LIVE_SMOKE=1 or use make live-smoke to run live smoke.")
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("OPENAI_MODEL"):
        pytest.skip("OPENAI_API_KEY and OPENAI_MODEL are required for live smoke.")

    from reliable_incident_agent.db import init_db
    from reliable_incident_agent.investigator import run_investigation

    init_db()
    trace = run_investigation("checkout_latency_spike", "candidate")

    assert trace.provider_metadata.provider == "openai"
    assert trace.provider_metadata.model == os.environ["OPENAI_MODEL"]
    assert trace.final_result.outcome in {"root_cause", "abstain"}
    assert trace.provider_metadata.response_ids
    assert 1 <= len(trace.tool_calls) <= 8
    assert any(call.status == "ok" for call in trace.tool_calls)
