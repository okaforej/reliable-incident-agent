"""One-command local launcher using the ignored OpenAI credential file."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Optional

from .db import init_db_if_missing

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KEY_FILE = ROOT / "openapi_key.md"
DEFAULT_MODEL = "gpt-5.6-terra"
KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")


def load_local_openai_env(
    key_file: Path,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Return a child-process environment without logging the credential."""

    try:
        raw = key_file.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"OpenAI credential file not found: {key_file}") from exc

    match = KEY_PATTERN.search(raw)
    if match is None:
        raise RuntimeError(
            f"No OpenAI API key was found in {key_file.name}."
        )

    child_env = dict(os.environ if environ is None else environ)
    child_env["OPENAI_API_KEY"] = match.group(0)
    child_env.setdefault("OPENAI_MODEL", DEFAULT_MODEL)
    existing_pythonpath = child_env.get("PYTHONPATH")
    source_path = str(ROOT / "src")
    child_env["PYTHONPATH"] = (
        f"{source_path}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else source_path
    )
    _ensure_node_on_path(child_env)
    return child_env


def _ensure_node_on_path(env: dict[str, str]) -> None:
    path_value = env.get("PATH", "")
    if shutil.which("node", path=path_value):
        return

    pnpm_command = env.get("PNPM", "pnpm")
    pnpm_location = shutil.which(pnpm_command, path=path_value)
    if pnpm_location is None:
        return
    pnpm_path = Path(pnpm_location)
    candidates = [pnpm_path.parent]
    if len(pnpm_path.parents) >= 3:
        candidates.append(pnpm_path.parents[2] / "node" / "bin")
    for candidate in candidates:
        if (candidate / "node").is_file():
            env["PATH"] = (
                f"{candidate}{os.pathsep}{path_value}" if path_value else str(candidate)
            )
            return


def _api_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "reliable_incident_agent.api:app",
        "--reload",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]


def _node_executable(env: dict[str, str]) -> str:
    _ensure_node_on_path(env)
    node = shutil.which("node", path=env.get("PATH", ""))
    if node is None:
        raise RuntimeError(
            "Node.js was not found. Install Node.js 20 or newer, then rerun make run."
        )
    return node


def _frontend_command(env: dict[str, str]) -> list[str]:
    return [
        _node_executable(env),
        str(ROOT / "node_modules" / "vite" / "bin" / "vite.js"),
        "--host",
        "0.0.0.0",
    ]


def _run_frontend(mode: str, env: dict[str, str]) -> int:
    node = _node_executable(env)
    if mode == "app":
        return _run_single(_frontend_command(env), env)
    if mode == "frontend-test":
        return _run_single(
            [node, str(ROOT / "node_modules" / "vitest" / "vitest.mjs"), "run"],
            env,
        )
    typecheck = _run_single(
        [
            node,
            str(ROOT / "node_modules" / "typescript" / "bin" / "tsc"),
            "--noEmit",
        ],
        env,
    )
    if typecheck:
        return typecheck
    return _run_single(
        [node, str(ROOT / "node_modules" / "vite" / "bin" / "vite.js"), "build"],
        env,
    )


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def _run_dev(env: dict[str, str]) -> int:
    init_db_if_missing()
    commands = [_api_command(), _frontend_command(env)]
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for command in commands:
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=ROOT,
                    env=env,
                    start_new_session=True,
                )
            )
        print(f"Open http://127.0.0.1:5173 — provider {env['OPENAI_MODEL']}", flush=True)
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    return return_code
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            _stop_process(process)


def _run_single(command: Sequence[str], env: dict[str, str]) -> int:
    try:
        return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode
    except KeyboardInterrupt:
        return 130


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=(
            "dev",
            "api",
            "app",
            "frontend-test",
            "frontend-build",
            "live-smoke",
        ),
        nargs="?",
        default="dev",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=Path(os.environ.get("OPENAI_KEY_FILE", DEFAULT_KEY_FILE)),
    )
    args = parser.parse_args(argv)
    key_file = args.key_file if args.key_file.is_absolute() else ROOT / args.key_file

    if args.mode in {"app", "frontend-test", "frontend-build"}:
        env = dict(os.environ)
        try:
            return _run_frontend(args.mode, env)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    try:
        env = load_local_openai_env(key_file)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.mode == "dev":
        try:
            return _run_dev(env)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.mode == "api":
        return _run_single(_api_command(), env)

    env["RUN_LIVE_SMOKE"] = "1"
    return _run_single(
        [sys.executable, "-m", "pytest", "-q", "live_tests", "-m", "live"],
        env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
