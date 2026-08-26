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
