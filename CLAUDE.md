# CLAUDE.md

> ✅ **REFACTOR LANDED** (branch `refactor/llamaindex-retrieval-pipeline`, work unit
> [`2026-05-30_20_llamaindex-retrieval-refactor`](.claude/work/2026-05-30_20_llamaindex-retrieval-refactor/state.json)).
> Retrieval is LlamaIndex-first: a **hierarchical `PropertyGraphIndex` on Neo4j**
> (79,882 docs / 5.82M leaf embeddings / 1.72M `LINKS_TO` edges) replaced Postgres + pgvector,
> FAISS, and the hand-rolled SQL retrieval — **all now deleted** (LIR-012). Workflows + the
> Chainlit UI consume the retriever (LIR-009/010). The benchmark suite was removed from this
> branch (archived on `archive/pre-llamaindex-refactor`). Pre-refactor state: `main` @ `5c3c8a8`.
> *Remaining: the live-UI tracing/feedback eyeball (LIR-011) is a manual step. Any lingering
> pgvector/FAISS/`EMA_RETRIEVER` mentions below are historical — see [`docs/RETRIEVAL.md`](docs/RETRIEVAL.md).*

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A Q&A benchmark and reference RAG implementations built from European Medicines Agency (EMA) human-regulatory content. Three separable deliverables:
- `corpus/corpus.jsonl` — normalized Q&A pairs mined from EMA HTML accordions and PDFs
- `benchmark/benchmark.jsonl` — ~30–50 stratified evaluation questions with gold answers (T1–T4 question types)
- `harness/` — MIRAGE-style evaluation pipeline with LLM judges

See `project_roadmap/ROADMAP.md` for the full phase-by-phase plan. See `project_roadmap/GLOSSARY.md` for regulatory and NLP terminology — consult it before guessing at pharma acronyms. Critical: **"AI" means Acceptable Intake (a toxicology limit in ng/day), not Artificial Intelligence**, in EMA Q&A documents.

## Key decisions already made

Read `DECISIONS.md` before planning any implementation. Short summary of the ones most likely to affect new code:

- **Retrieval framework:** LlamaIndex — hierarchical **`PropertyGraphIndex` on Neo4j** (refactor in progress on branch `refactor/llamaindex-retrieval-pipeline`; replaces the former pgvector + FAISS paths). See `docs/RETRIEVAL.md`.
- **Site structure is the retrieval signal.** Page→PDF/page hyperlinks become `LINKS_TO` edges and section hierarchy becomes `PARENT_OF` edges in Neo4j; the retriever walks them (small-to-big + `links_to`) when semantic search underfetches. *(Historical note: the MIGR-018..025 `link_graph`/recursive-CTE machinery was documented as shipped but **never actually built** — see `docs/RETRIEVAL.md`. Links are now extracted at ingest from `web_items.html_raw` by `harness.indexing.links`.)*
- **Tracing:** Arize Phoenix + OpenInference — model-agnostic, self-hosted, wired in `run_eval.py`
- **Feedback store:** Phoenix annotations API — no separate database
- **Semantic cache:** thin FAISS index over past query embeddings (`harness/index/query_cache.faiss`) — GPTCache is abandoned, do not use it
- **Learning from feedback:** runtime few-shot injection from rated trajectories — no model training, no DSPy yet
- **Credentials:** `~/.myenvs/ema_nlp.env` via python-dotenv — never in the repo

Open decisions not yet made are in `OPEN_QUESTIONS.md`.

## Current project phase

**Phase 1 — corpus extraction complete.** `corpus/corpus.jsonl` has 26,251 Q&A records (17,505 HTML + 8,746 PDF).

Completed: TASK-001 through TASK-007 (Phase 0 scoping, Phase 1 extractors, corpus writer, MongoDB adaptor) + PDF-001–PDF-004 (parsed PDF ingest pipeline; 65k docs in `parsed_pdfs` collection).

Next phase: **Phase 2 — benchmark construction** (curate 30–50 evaluation questions, T1–T4 types).  
Full task list and status: `.claude/work/2026-05-10_02_implementation-plan/state.json`

**Current work — retrieval refactor** (branch `refactor/llamaindex-retrieval-pipeline`): retrieval is being rebuilt LlamaIndex-first on Neo4j (`harness/indexing/`, hierarchical `PropertyGraphIndex`). Offline pipeline built + verified on a CPU subset (LIR-001..008); workflow/chat-UI re-seam + old-stack deletion pending (LIR-009..014). The benchmark/eval suite was removed from this branch (archived on `archive/pre-llamaindex-refactor`). See [`docs/RETRIEVAL.md`](docs/RETRIEVAL.md) and `.claude/work/2026-05-30_20_llamaindex-retrieval-refactor/`.

## Data sources

> **Starting the data services:** `scripts/start_services.sh` brings up MongoDB (`deploy/mongo/`) and Neo4j (`deploy/neo4j/`) as Docker containers and health-checks them. *(Postgres/pgvector is being removed by the retrieval refactor — see `docs/RETRIEVAL.md`.)* On this host (kernel ≥ 6.19) MongoDB **must** run via the pinned `mongo:8.0.4` container — the native package crashes (SERVER-121912). See `deploy/mongo/README.md` and `deploy/neo4j/README.md`.

- **MongoDB** `ema_scraper.web_items` — raw scraped EMA pages; HTML stored as `html_raw` (1-element list), PDFs as metadata only
- **MongoDB** `ema_scraper.parsed_pdfs` — pymupdf4llm markdown keyed by URL; built by `scripts/ingest_parsed_pdfs.py --legacy`; 65k docs; query `{error: ""}` for clean parses
- **MongoDB** `ema_scraper.parsed_documents` (MIGR-001) — canonical parser-output sink. One row per `(url, parser, parser_version)`. Populated by `corpus/parsers/*.py` CLIs. **Ingestion source for `harness.indexing.ingest`.** *(Not backfilled at scale on this host — `scripts/backfill_parsed_documents_subset.py` seeds a verify subset; see `docs/RETRIEVAL.md`.)*
- **`ema_scraper.link_graph` — never built.** Older docs (MIGR-018..025) describe this collection; it was never populated here. Links are extracted at ingest time from `web_items.html_raw` by `harness.indexing.links.extract_links` and become `LINKS_TO` edges in Neo4j.
- **Neo4j** (Docker, `deploy/neo4j/`) — the retrieval store: a LlamaIndex `PropertyGraphIndex` of `:Document` + `:Chunk` nodes with `HAS_CHUNK`/`PARENT_OF`/`LINKS_TO` edges and a native vector index over chunk embeddings. Built by `harness.indexing.build_index` from Mongo `parsed_documents`. This is the retrieval target; `corpus.jsonl` is benchmark-only. See `docs/RETRIEVAL.md`. *(Replaces the former Postgres+pgvector store, being removed in the refactor.)*
- **Nextcloud**: `~/Nextcloud/Datasets/` — Scrapy cache (`ema_scraper/cache/`) + IDMP ontology RDF files
- Paths are configured in `config.py`, which loads `~/.myenvs/ema_nlp.env` via python-dotenv
- MongoDB source adaptors: `corpus/sources/mongo_source.py` yields `QARecord` for the Q&A pipeline; `corpus/sources/parsed_documents.py` exposes the writer and index bootstrap for the parsers layer; `corpus/sources/synthetic_legacy_reader.py` (MIGR-008) bridges `parsed_pdfs` + `web_items` rows to the sync as a transition fixture until MIGR-013 backfills.
- Retrieval is selected by `EMA_INDEX_PROFILE` (default `neo4j_hier` → `harness/configs/index/*.yaml`). See `docs/RETRIEVAL.md`. *(The old `EMA_RETRIEVER=faiss|pgvector` switch is removed.)*

## Commands

```bash
pip install -e ".[dev]"       # install project + dev deps (or: uv pip install -e ".[dev]")
scripts/start_services.sh     # start MongoDB + Neo4j (Docker) and health-check them
pytest                        # run all tests
pytest tests/path/to/test.py  # run a single test file
ruff check .                  # lint
ruff check --fix .            # lint with auto-fix
mypy .                        # type check
```

## Project phase

Currently in **Phase 1 (corpus extraction)**. Do not introduce work from later phases without asking. The full phase sequence and success criteria per phase are in `project_roadmap/ROADMAP.md`.

## V1 scope locks

- EMA human-regulatory content only — no FDA content, no clinical trial documents. **(2026-06-02: EPARs are now IN scope for the narrative retrieval corpus** — the ~18k EPAR assessment reports in `parsed_documents` are indexed into Neo4j. The earlier "No EPARs" lock is lifted *for retrieval*; benchmark Q&A curation scope is unchanged.)
- **Narrative corpus is in scope** (the full PDF + HTML body text, indexed into the Neo4j `PropertyGraphIndex` as `:Document`/`:Chunk` nodes). `corpus.jsonl` is the curated Q&A pair extract — used by the benchmark only; runtime retrieval is over the Neo4j chunk vector index + graph edges (see `docs/RETRIEVAL.md`).
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
