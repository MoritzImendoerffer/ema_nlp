# Gates and everyday commands. All of them use .venv's Python, never whatever `python`
# resolves to: on the maintainer's machine `python3` is conda's Python 3.9, which holds none
# of this project's packages. Build .venv with scripts/setup.sh (docs/SETUP.md).

PY := .venv/bin/python

.PHONY: help test test-live test-parse parse-env lint fmt pm all

help:
	@echo "make test       pytest without the tests marked integration: no MongoDB, no Neo4j, no model call"
	@echo "make test-live  the tests marked integration: they read the live MongoDB on localhost:27017"
	@echo "make parse-env  build the Docling parse environment at config.DOCLING_ENV (never .venv)"
	@echo "make test-parse the tests marked parse, in the parse environment; reported, not a gate"
	@echo "make lint       ruff check ."
	@echo "make fmt        ruff check --fix ."
	@echo "make pm         regenerate docs/pm/ from the active work unit"
	@echo "make all        test and lint, the two gates"

# The gate is the part that gives the same answer on every machine. On 2026-11-23 it ran
# 692 tests in 14 seconds. The 7 tests of tests/test_mongo_source.py need a populated
# MongoDB, so they are a target of their own.
test:
	$(PY) -m pytest -m "not integration and not parse"

test-live:
	$(PY) -m pytest -m integration

# The Docling parser runs in its own environment (backlog row 17): Docling would move the
# torch build under the embedding model in .venv.
DOCLING_PY = $(shell $(PY) -c 'import config; print(config.DOCLING_ENV)')/bin/python

parse-env:
	bash scripts/setup_parse_env.sh

test-parse:
	$(DOCLING_PY) -m pytest -m parse tests/test_docling_parse_env.py

lint:
	$(PY) -m ruff check .

fmt:
	$(PY) -m ruff check --fix .

# The board script uses the standard library only, and needs Python 3.10 or newer.
pm:
	$(PY) scripts/pm_notes.py

all: test lint
