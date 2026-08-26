.PHONY: install run seed api app build demo test live-smoke lint

BUNDLED_PNPM := /Users/meka/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm
PNPM ?= $(if $(wildcard $(BUNDLED_PNPM)),$(BUNDLED_PNPM),pnpm)
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
VENV ?= .venv
PY_DEPS_STAMP := $(VENV)/.dependencies-installed
NODE_DEPS_STAMP := node_modules/.dependencies-installed

install: $(PY_DEPS_STAMP) $(NODE_DEPS_STAMP)

$(PY_DEPS_STAMP): requirements.txt
	test -x $(VENV)/bin/python || python3 -m venv $(VENV)
	$(VENV)/bin/python -m pip install -r requirements.txt
	touch $(PY_DEPS_STAMP)

$(NODE_DEPS_STAMP): package.json pnpm-lock.yaml
	@if command -v "$(PNPM)" >/dev/null 2>&1; then \
		"$(PNPM)" install; \
	elif command -v corepack >/dev/null 2>&1; then \
		corepack pnpm install; \
	elif command -v npx >/dev/null 2>&1; then \
		npx --yes pnpm@11.19.0 install; \
	else \
		echo "Node package setup needs pnpm, corepack, or npx." >&2; \
		exit 1; \
	fi
	touch $(NODE_DEPS_STAMP)

run: install
	@echo "Starting API and UI; the first Python import may take a moment..."
	@PYTHONPATH=src PNPM="$(PNPM)" $(VENV)/bin/python -m reliable_incident_agent.local_dev dev

seed:
	PYTHONPATH=src $(PYTHON) -c "from reliable_incident_agent.db import init_db; print(init_db())"

api: install
	@PYTHONPATH=src $(VENV)/bin/python -m reliable_incident_agent.local_dev api

app: install
	@PYTHONPATH=src PNPM="$(PNPM)" $(VENV)/bin/python -m reliable_incident_agent.local_dev app

build: install
	@PYTHONPATH=src PNPM="$(PNPM)" $(VENV)/bin/python -m reliable_incident_agent.local_dev frontend-build

demo:
	PYTHONPATH=src $(PYTHON) scripts/run_demo.py

test: install
	PYTHONPATH=src $(PYTHON) -m pytest -q tests
	@PYTHONPATH=src PNPM="$(PNPM)" $(VENV)/bin/python -m reliable_incident_agent.local_dev frontend-test

live-smoke: install
	@PYTHONPATH=src $(VENV)/bin/python -m reliable_incident_agent.local_dev live-smoke

lint:
	PYTHONPATH=src $(PYTHON) -m ruff check --ignore UP045 src tests live_tests scripts
