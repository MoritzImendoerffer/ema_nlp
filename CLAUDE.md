# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A Q&A benchmark and reference RAG implementations built from European Medicines Agency (EMA) human-regulatory content. Three separable deliverables:
- `corpus/corpus.jsonl` — normalized Q&A pairs mined from EMA HTML accordions and PDFs
- `benchmark/benchmark.jsonl` — ~30–50 stratified evaluation questions with gold answers (T1–T4 question types)
- `harness/` — MIRAGE-style evaluation pipeline with LLM judges

See `project_roadmap/ROADMAP.md` for the full phase-by-phase plan. See `project_roadmap/GLOSSARY.md` for regulatory and NLP terminology — consult it before guessing at pharma acronyms. Critical: **"AI" means Acceptable Intake (a toxicology limit in ng/day), not Artificial Intelligence**, in EMA Q&A documents.

## Data sources

- **MongoDB**: `localhost:27017`, database `ema_scraper`, collection `web_items` — scraped EMA website content from the companion repo [ema_scraper](https://github.com/MoritzImendoerffer/ema_scraper)
- **Nextcloud**: `~/Nextcloud/Datasets/` — local dataset storage including IDMP ontology RDF files
- Paths are configured in `config.py`

## Commands

```bash
pytest                        # run all tests
pytest tests/path/to/test.py  # run a single test file
ruff check .                  # lint
ruff check --fix .            # lint with auto-fix
mypy .                        # type check
```

No build step. No package install command yet — a `pyproject.toml` or `requirements.txt` will be added as dependencies accumulate.

## Project phase

Currently in **Phase 0 (scoping)**. Do not introduce work from later phases without asking. The full phase sequence and success criteria per phase are in `project_roadmap/ROADMAP.md`.

## V1 scope locks

- EMA human-regulatory Q&As only. No EPARs, no FDA content, no clinical trial documents.
- No ontology/graph infrastructure (IDMP, SPOR, Neo4j) — deferred to v2+. `idmp_dabbling.py` is exploratory scratch.
- No multilingual content.
- Every added complexity layer must be justified by a specific benchmark failure, not anticipation.

## Data conventions

- All data files are JSONL, one record per line
- Q&A corpus record schema is defined in `project_roadmap/ROADMAP.md` Phase 1.1
- Benchmark item schema is defined in `project_roadmap/ROADMAP.md` Phase 2.3
- LLM prompts live in files, not as string literals in code
- Each eval run config goes under `harness/configs/`; results under `results/<run_id>/` with config dumped alongside
- Raw scraped data (large artifacts) must not be committed

## Work history

After completing any work unit saved under `.claude/work/`, append one row to `.claude/HISTORY.md` with: today's date, a one-sentence summary of the instruction, and a relative link to the primary findings markdown. Do not read HISTORY.md automatically at session start — only consult it when the user asks about past work.

## Evaluation design notes

The benchmark uses four question types (T1 Lookup, T2 Scoping, T3 Multi-hop, T4 Synthesis) — always report metrics broken down by type, not aggregate only. The headline metric is **lift** (open-book minus closed-book), not absolute correctness, to handle training-data contamination. See `project_roadmap/LEAKAGE.md` for the full contamination treatment. See `project_roadmap/ABLATIONS.md` for the three planned ablations (A: evidence filtering, B: process-reward agent, C: prompting matrix across model tiers).
