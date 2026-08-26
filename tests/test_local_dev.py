from __future__ import annotations

from pathlib import Path

import pytest


def test_local_launcher_reads_key_file_without_overriding_selected_model(
    tmp_path: Path,
) -> None:
    from reliable_incident_agent.local_dev import load_local_openai_env

    key_file = tmp_path / "openapi_key.md"
    key_file.write_text("OPENAI_API_KEY=sk-test-1234567890abcdef\n")

    env = load_local_openai_env(
        key_file,
        {"OPENAI_MODEL": "test-model", "PYTHONPATH": "existing"},
    )

    assert env["OPENAI_API_KEY"] == "sk-test-1234567890abcdef"
    assert env["OPENAI_MODEL"] == "test-model"
    assert env["PYTHONPATH"].endswith("existing")


def test_local_launcher_uses_default_model(tmp_path: Path) -> None:
    from reliable_incident_agent.local_dev import DEFAULT_MODEL, load_local_openai_env

    key_file = tmp_path / "openapi_key.md"
    key_file.write_text("Credential: sk-test-abcdef1234567890\n")

    env = load_local_openai_env(key_file, {})

    assert env["OPENAI_MODEL"] == DEFAULT_MODEL


def test_local_launcher_rejects_missing_key_without_echoing_file_contents(
    tmp_path: Path,
) -> None:
    from reliable_incident_agent.local_dev import load_local_openai_env

    key_file = tmp_path / "openapi_key.md"
    key_file.write_text("not-a-secret-value\n")

    with pytest.raises(RuntimeError, match="No OpenAI API key") as error:
        load_local_openai_env(key_file, {})

    assert "not-a-secret-value" not in str(error.value)


def test_local_launcher_finds_node_beside_bundled_pnpm(tmp_path: Path) -> None:
    from reliable_incident_agent.local_dev import load_local_openai_env

    key_file = tmp_path / "openapi_key.md"
    key_file.write_text("sk-test-abcdef1234567890\n")
    dependencies = tmp_path / "dependencies"
    fallback = dependencies / "bin" / "fallback"
    node_bin = dependencies / "node" / "bin"
    fallback.mkdir(parents=True)
    node_bin.mkdir(parents=True)
    pnpm = fallback / "pnpm"
    node = node_bin / "node"
    pnpm.write_text("#!/bin/sh\n")
    node.write_text("#!/bin/sh\n")
    pnpm.chmod(0o700)
    node.chmod(0o700)

    env = load_local_openai_env(
        key_file,
        {"PATH": str(fallback), "PNPM": str(pnpm)},
    )

    assert env["PATH"].split(":", maxsplit=1)[0] == str(node_bin)


def test_frontend_mode_does_not_require_openai_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from reliable_incident_agent import local_dev

    captured: dict[str, object] = {}

    def run_single(command: list[str], env: dict[str, str]) -> int:
        captured["command"] = command
        captured["has_key"] = "OPENAI_API_KEY" in env
        return 0

    monkeypatch.setattr(local_dev, "_node_executable", lambda env: "node")
    monkeypatch.setattr(local_dev, "_run_single", run_single)

    result = local_dev.main(
        ["frontend-test", "--key-file", str(tmp_path / "missing.md")]
    )

    assert result == 0
    command = captured["command"]
    assert isinstance(command, list)
    assert command[-1] == "run"
    assert str(command[-2]).endswith("node_modules/vitest/vitest.mjs")
    assert captured["has_key"] is False


def test_init_db_if_missing_preserves_existing_database(tmp_path: Path) -> None:
    from reliable_incident_agent.db import init_db_if_missing

    database = tmp_path / "existing.sqlite"
    database.write_bytes(b"existing investigation history")

    initialized = init_db_if_missing(
        database,
        tmp_path / "seed-that-must-not-be-read.sql",
    )

    assert initialized == database
    assert database.read_bytes() == b"existing investigation history"


def test_init_db_if_missing_seeds_a_missing_database(tmp_path: Path) -> None:
    from sqlalchemy import text

    from reliable_incident_agent.db import get_engine, init_db_if_missing

    database = tmp_path / "missing.sqlite"
    seed = tmp_path / "seed.sql"
    seed.write_text("CREATE TABLE marker (value TEXT); INSERT INTO marker VALUES ('seeded');")

    initialized = init_db_if_missing(database, seed)

    with get_engine(database).connect() as connection:
        value = connection.execute(text("SELECT value FROM marker")).scalar_one()
    assert initialized == database
    assert value == "seeded"


def test_dev_launcher_uses_non_destructive_database_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reliable_incident_agent import local_dev

    initialized = 0

    def initialize() -> None:
        nonlocal initialized
        initialized += 1

    class FinishedProcess:
        def poll(self) -> int:
            return 0

    monkeypatch.setattr(local_dev, "init_db_if_missing", initialize)
    monkeypatch.setattr(local_dev, "_api_command", lambda: ["api"])
    monkeypatch.setattr(local_dev, "_frontend_command", lambda _env: ["frontend"])
    monkeypatch.setattr(local_dev.subprocess, "Popen", lambda *_args, **_kwargs: FinishedProcess())
    monkeypatch.setattr(local_dev, "_stop_process", lambda _process: None)

    result = local_dev._run_dev({"OPENAI_MODEL": "test-model"})

    assert result == 0
    assert initialized == 1
