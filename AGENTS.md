# Reliable Incident Agent — Codex Operating Contract

`COORDINATION.md` is the architecture and product source of truth. If code, tests, README text, historical handoffs, or this file conflict with it, `COORDINATION.md` wins.

## Roles

- The primary Codex task is the architect and coordinator. It owns architecture decisions, workstream boundaries, integration review, and final acceptance.
- Codex SWE agents implement bounded workstreams. They must read `COORDINATION.md` before editing and remain inside the ownership declared in their assignment.
- Independent verifier agents are read-only unless the architect explicitly reassigns them to implementation.
- GitHub Copilot is not an active implementation or coordination component.

## Working rules

- Preserve the dirty worktree and unrelated user files. Do not commit unless the user explicitly asks.
- Do not edit another agent's owned files while that agent is active.
- Report files changed, tests run, failures, and unresolved architecture questions at handoff.
- Live model calls require explicit credentials and an opt-in path. Never expose, log, or commit secrets.
- Keep model-backed work behind explicit POST actions. GET requests, page load, and scenario selection remain read-only.
- Never substitute fixtures or recorded results after an API/provider failure.
- The only state-changing capability is the confirmed checkout database-pool rollback defined in `COORDINATION.md`.
- RCA correctness remains separate from Grounding, Investigation Sufficiency, Tool Efficiency, and their Behavioral SLO composite.

## Acceptance gates

Run, at minimum:

```bash
make seed
make test
make lint
make build
git diff --check
```

For UI work, also verify the real frontend/backend request contracts and exercise the local UI at desktop and mobile widths. Run `make live-smoke` only as an explicit opt-in with both `OPENAI_API_KEY` and `OPENAI_MODEL` configured.
