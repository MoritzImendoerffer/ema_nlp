# Gates and everyday commands. All of them use .venv's Python, never whatever `python`
# resolves to: on the maintainer's machine `python3` is conda's Python 3.9, which holds none
# of this project's packages. Build .venv with scripts/setup.sh (docs/SETUP.md).

PY := .venv/bin/python

.PHONY: help test test-live lint fmt pm all

help:
	@echo "make test       pytest without the tests marked integration: no MongoDB, no Neo4j, no model call"
	@echo "make test-live  the tests marked integration: they read the live MongoDB on localhost:27017"
	@echo "make lint       ruff check ."
	@echo "make fmt        ruff check --fix ."
	@echo "make pm         regenerate docs/pm/ from the active work unit"
	@echo "make all        test and lint, the two gates"

# The gate is the part that gives the same answer on every machine. On 2026-11-23 it ran
# 692 tests in 14 seconds. The 7 tests of tests/test_mongo_source.py need a populated
# MongoDB, so they are a target of their own.
test:
	$(PY) -m pytest -m "not integration"

test-live:
	$(PY) -m pytest -m integration

lint:
	$(PY) -m ruff check .

fmt:
	$(PY) -m ruff check --fix .

# The board script uses the standard library only, and needs Python 3.10 or newer.
pm:
	$(PY) scripts/pm_notes.py

all: test lint
