"""CLI entrypoint for repeatable local demo runs."""

from __future__ import annotations

import argparse
import json

from agent import run_investigation
from tools import load_incidents


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Reliable Incident Agent demo.")
    parser.add_argument("--incident", default=None, help="Incident id. Defaults to the first fixture.")
    parser.add_argument("--mode", choices=["reliable", "weak"], default="reliable")
    args = parser.parse_args()

    incidents = load_incidents()
    if not incidents:
        raise SystemExit("No incidents found in data/incidents.json")
    incident_id = args.incident or incidents[0]["id"]
    trace = run_investigation(incident_id, mode=args.mode)
    print(json.dumps(trace.to_dict(), indent=2))


if __name__ == "__main__":
    main()
