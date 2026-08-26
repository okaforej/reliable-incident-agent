.PHONY: install seed api app build demo test lint

PNPM ?= /Users/meka/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm
NODE_BIN ?= /Users/meka/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin
export PATH := $(NODE_BIN):$(PATH)

install:
	python3 -m pip install -r requirements.txt
	$(PNPM) install

seed:
	PYTHONPATH=src python3 -c "from reliable_incident_agent.db import init_db; print(init_db())"

api:
	PYTHONPATH=src python3 -m uvicorn reliable_incident_agent.api:app --reload --host 127.0.0.1 --port 8000

app:
	$(PNPM) run dev

build:
	$(PNPM) run build

demo:
	PYTHONPATH=src python3 scripts/run_demo.py

test:
	PYTHONPATH=src python3 -m pytest -q

lint:
	PYTHONPATH=src python3 -m ruff check src tests scripts
