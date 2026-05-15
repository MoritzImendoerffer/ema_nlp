# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A Q&A benchmark and reference RAG implementations built from European Medicines Agency (EMA) human-regulatory content. Three separable deliverables:
- `corpus/corpus.jsonl` — normalized Q&A pairs mined from EMA HTML accordions and PDFs
- `benchmark/benchmark.jsonl` — ~30–50 stratified evaluation questions with gold answers (T1–T4 question types)
- `harness/` — MIRAGE-style evaluation pipeline with LLM judges

See `project_roadmap/ROADMAP.md` for the full phase-by-phase plan. See `project_roadmap/GLOSSARY.md` for regulatory and NLP terminology — consult it before guessing at pharma acronyms. Critical: **"AI" means Acceptable Intake (a toxicology limit in ng/day), not Artificial Intelligence**, in EMA Q&A documents.

## Key decisions already made

Read `DECISIONS.md` before planning any implementation. Short summary of the ones most likely to affect new code:

- **Retrieval framework:** LlamaIndex (`DocumentSummaryIndex`, `NodeRelationship`, `ReActAgent`)
- **Tracing:** Arize Phoenix + OpenInference — model-agnostic, self-hosted, wired in `run_eval.py`
- **Feedback store:** Phoenix annotations API — no separate database
- **Semantic cache:** thin FAISS index over past query embeddings (`harness/index/query_cache.faiss`) — GPTCache is abandoned, do not use it
- **Learning from feedback:** runtime few-shot injection from rated trajectories — no model training, no DSPy yet
- **Credentials:** `~/.myenvs/ema_nlp.env` via python-dotenv — never in the repo

Open decisions not yet made are in `OPEN_QUESTIONS.md`.

## Current project phase

**Phase 1 — corpus extraction.** Next task: **TASK-007** (deduplication + landing page filter + corpus writer).

Completed: TASK-001 through TASK-006 (Phase 0 scoping + Phase 1 extractors).  
Full task list and status: `.claude/work/2026-05-10_02_implementation-plan/state.json`

## Data sources

- **MongoDB**: `localhost:27017`, database `ema_scraper`, collection `web_items` — scraped EMA website content from the companion repo [ema_scraper](https://github.com/MoritzImendoerffer/ema_scraper)
- **Nextcloud**: `~/Nextcloud/Datasets/` — local dataset storage including IDMP ontology RDF files
- Paths are configured in `config.py`, which loads `~/.myenvs/ema_nlp.env` via python-dotenv

## Commands

```bash
pip install -e ".[dev]"       # install project + dev deps (or: uv pip install -e ".[dev]")
pytest                        # run all tests
pytest tests/path/to/test.py  # run a single test file
ruff check .                  # lint
ruff check --fix .            # lint with auto-fix
mypy .                        # type check
```

## Project phase

Currently in **Phase 1 (corpus extraction)**. Do not introduce work from later phases without asking. The full phase sequence and success criteria per phase are in `project_roadmap/ROADMAP.md`.

## V1 scope locks

- EMA human-regulatory Q&As only. No EPARs, no FDA content, no clinical trial documents.
- No ontology/graph infrastructure (IDMP, SPOR, Neo4j) — deferred to v2+. IDMP RDF used only for lightweight node metadata tagging (TASK-016.5). `idmp_dabbling.py` is exploratory scratch.
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

After **any interaction that results in code or config changes**, append one row to `.claude/HISTORY.md`. The table has five columns:

| Column | Content |
|--------|---------|
| Date | `YYYY-MM-DD` |
| Summary | One sentence on what was done (outcome, not the request) |
| Changed | Comma-separated files or dirs touched (e.g. `config.py`, `scripts/`) |
| Phase | Current roadmap phase (e.g. `Phase 1`) |
| Work unit | Relative link to `.claude/work/` doc if one exists, else `—` |

Do not read HISTORY.md at session start — only when the user asks about past work. The file is never auto-loaded, so it does not consume context window.

## Evaluation design notes

The benchmark uses four question types (T1 Lookup, T2 Scoping, T3 Multi-hop, T4 Synthesis) — always report metrics broken down by type, not aggregate only. The headline metric is **lift** (open-book minus closed-book), not absolute correctness, to handle training-data contamination. See `project_roadmap/LEAKAGE.md` for the full contamination treatment. See `project_roadmap/ABLATIONS.md` for the three planned ablations (A: evidence filtering, B: process-reward agent, C: prompting matrix across model tiers).
