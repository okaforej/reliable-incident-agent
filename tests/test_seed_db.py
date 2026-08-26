from __future__ import annotations

import sqlite3

from conftest import EXPECTED_RCA, PROJECT_ROOT, SCENARIO_ID, import_module

REQUIRED_TABLES = {
    "scenarios",
    "incidents",
    "services",
    "dependencies",
    "metrics",
    "metric_points",
    "logs",
    "changes",
    "expected_outcomes",
    "investigation_runs",
    "tool_calls",
    "evaluations",
    "comparisons",
    "chat_messages",
    "action_proposals",
    "replay_instances",
}


def _table_contains_text(conn: sqlite3.Connection, table: str, expected_text: str) -> bool:
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    for column in columns:
        query = f"SELECT 1 FROM {table} WHERE CAST({column} AS TEXT) = ? LIMIT 1"
        if conn.execute(query, (expected_text,)).fetchone():
            return True
    return False


def test_seed_database_exists_with_required_tables_and_scenario_data() -> None:
    db = import_module("db")
    assert hasattr(db, "init_db"), "Expected reliable_incident_agent.db.init_db to seed SQLite."
    db.init_db()

    db_path = PROJECT_ROOT / "var" / "replays.sqlite"
    assert db_path.exists()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert REQUIRED_TABLES <= tables
        assert _table_contains_text(conn, "scenarios", SCENARIO_ID)
        assert _table_contains_text(conn, "scenarios", "payments_gateway_timeout")
        assert _table_contains_text(conn, "scenarios", "insufficient_frontend_evidence")
        assert _table_contains_text(conn, "expected_outcomes", EXPECTED_RCA)
        checkout_description = conn.execute(
            "SELECT description FROM scenarios WHERE id = ?",
            (SCENARIO_ID,),
        ).fetchone()[0]
        checkout_symptoms = conn.execute(
            "SELECT symptoms_json FROM incidents WHERE scenario_id = ?",
            (SCENARIO_ID,),
        ).fetchone()[0]
        assert "caused by" not in checkout_description.lower()
        assert "postgres" not in checkout_symptoms.lower()
        assert "max_connections" not in checkout_symptoms.lower()
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM scenarios")
        }
        assert names == {
            "Checkout Latency Spike",
            "Payment Submission Failures",
            "Frontend Error Spike",
        }
        public_seed_text = repr(names).lower()
        for forbidden in ("db pool", "exhaustion", "gateway timeout", "insufficient", "inconclusive"):
            assert forbidden not in public_seed_text


def test_active_replay_does_not_expose_post_action_evidence() -> None:
    from reliable_incident_agent.replay import ReplayRepository

    repo = ReplayRepository()
    replay_instance_id = repo.create_replay_instance(SCENARIO_ID)
    active_checkout_metrics = repo.get_metrics(
        SCENARIO_ID,
        "checkout",
        "http.server.duration.p95_ms",
        replay_instance_id,
    )
    active_checkout_logs = repo.search_logs(
        SCENARIO_ID,
        "checkout",
        replay_instance_id=replay_instance_id,
    )
    active_checkout_changes = repo.get_recent_changes(
        SCENARIO_ID,
        "checkout",
        replay_instance_id,
    )

    assert all(point["ts"] != "2026-08-24T09:45:00Z" for point in active_checkout_metrics[0]["points"])
    assert all(log["id"] != "log_checkout_recovered_after_rollback" for log in active_checkout_logs)
    assert active_checkout_changes[0]["details"]["config_key"] == "db.max_open_connections"
    assert "rolled_back_at" not in active_checkout_changes[0]["details"]

    repo.rollback_checkout_pool(replay_instance_id)
    mitigated_checkout_metrics = repo.get_metrics(
        SCENARIO_ID,
        "checkout",
        "http.server.duration.p95_ms",
        replay_instance_id,
    )
    mitigated_checkout_logs = repo.search_logs(
        SCENARIO_ID,
        "checkout",
        replay_instance_id=replay_instance_id,
    )
    mitigated_checkout_changes = repo.get_recent_changes(
        SCENARIO_ID,
        "checkout",
        replay_instance_id,
    )

    assert any(point["ts"] == "2026-08-24T09:45:00Z" for point in mitigated_checkout_metrics[0]["points"])
    assert any(log["id"] == "log_checkout_recovered_after_rollback" for log in mitigated_checkout_logs)
    assert "rolled_back_at" in mitigated_checkout_changes[0]["details"]
