# CLAUDE.md

> ✅ **REFACTOR LANDED** (branch `refactor/llamaindex-retrieval-pipeline`, work unit
> [`2026-05-30_20_llamaindex-retrieval-refactor`](.claude/work/2026-05-30_20_llamaindex-retrieval-refactor/state.json)).
> Retrieval is LlamaIndex-first: a **hierarchical `PropertyGraphIndex` on Neo4j**
> (79,882 docs / 5.82M leaf embeddings / 99,520 main-content-scoped `LINKS_TO` edges, work unit 24)
> replaced Postgres + pgvector, FAISS, and the hand-rolled SQL retrieval — **all now deleted**
> (LIR-012, 2026-06-03). The recipe engine + Chainlit UI consume the retriever (LIR-009/010,
> 2026-06-02, originally via the since-retired workflows), with live MLflow tracing/feedback
> wired in `app.py`. Pre-refactor state: `main` @ `5c3c8a8`. *(The pre-refactor eval suite was
> archived on `archive/pre-llamaindex-refactor`; a recipe-based eval runner has since been
> rebuilt — see the recipe-engine banner.)*
> *See [`docs/RETRIEVAL.md`](docs/RETRIEVAL.md) for the full retrieval picture.*

> 🧪 **Agentic layer — runtime-verified** (branch `claude/agentic-rag-foundation`).
> A LlamaIndex `FunctionAgent` + tool-registry orchestration with Pydantic structured output
> (`RegulatoryAnswer`), a config-driven retrieval pipeline (query-expansion + rerank), MLflow
> run-recording + autolog + `mlflow.genai` judges, and typed ontology enrichment live under
> `harness/{schemas,tools,agents,retrieval,obs,ontology,eval}/`. **Verified end-to-end on the
> GPU host (2026-06-22, T1–T6):** offline tests, the agent demo, MLflow autolog (traces
> complete — the mlflow#13352 hang did not occur), ontology enrichment into Neo4j, and
> judges/eval all run. It started as an additive "Agentic RAG" mode in `app.py`; the agent is
> now the **only** engine (see the recipe banner below — the old workflows are deleted). The
> live app **and** the agent are **MLflow-traced** with 👍/👎 logged as MLflow trace
> assessments — Arize Phoenix was fully removed in the 2026-06-22 migration; `run_ui.sh`
> starts the MLflow server on :5000. *How-to:
> [`docs/AGENTIC_GUIDE.md`](docs/AGENTIC_GUIDE.md). Design: [`docs/TARGET_ARCHITECTURE.md`](docs/TARGET_ARCHITECTURE.md).
> Verification runbook + results: [`docs/RUNTIME_VERIFICATION.md`](docs/RUNTIME_VERIFICATION.md).*

> 🍳 **Recipe engine — config-driven, single-engine agentic RAG** (this branch).
> There is **one engine**: a LlamaIndex `FunctionAgent`. The UI/eval select a **recipe**
> (`harness/configs/recipes/*.yaml` + `$EMA_CONFIG_DIR`) = orchestration (system prompt + tools
> + output schema) + retrieval (index profile + optional pipeline + few-shot) + generation +
> an optional inline judge layer. RAG *techniques are tools + instructions*, not separate
> engines — Naive RAG → the agent with one `ema_search` tool; **CRAG → `corrective_search`**
> (a bounded grade/rewrite loop, single-sourced in `harness/retrieval/corrective.py`); ReAct →
> the agent's native tool loop. A single Chainlit **recipe dropdown** replaces the old
> workflow/prompt/profile selectors; the resolved recipe is stamped honestly on every MLflow
> trace; 👍/👎 also feeds the rated-trajectory few-shot cache. *How-to:
> [`docs/RECIPES.md`](docs/RECIPES.md); techniques + citations: [`docs/RAG_TECHNIQUES.md`](docs/RAG_TECHNIQUES.md).*
> **The legacy `harness/workflows/*` Workflow engine was deleted (2026-06-25) — fully retired
> in favour of recipes.** Recipes are the **single composition path**: `build_recipe` →
> `AgentWorkflowAdapter` (`build_session` + `configs/agent/*.yaml` were absorbed, 2026-07-04).
> **Eval vehicle:** `scripts/run_eval.py` runs a recipe over `benchmark/benchmark.jsonl`
> (45 items) — one MLflow run per question type with `mlflow.genai` judges; MLflow is the
> system of record for results. *(Doc sweeps 2026-06-25 + 2026-07-05 brought the docs in
> line; `docs/WORKFLOWS.md` + `docs/RETRIEVAL_TRACKS.md` are intentionally-preserved history
> behind SUPERSEDED banners.)*

> 📎 **Citations: attribution + SME review + export** (2026-07-07, this branch).
> Claims are **verbatim answer spans** (prompt + schema contract); `harness/attribution.py`
> locates them (exact→fuzzy), numbers references by first use, and injects clickable `[n]`
> markers into the chat answer. Under each answer: a persistent **CitationReview** custom
> element (`public/elements/CitationReview.jsx`) — side-by-side answer/reference view with
> per-citation SME verdicts (`supports|partial|no` + "prefer <category>" + note) logged as
> MLflow trace assessments (`log_citation_feedback`, unique `citation_<rank>_<chunk8>`
> names). Per-turn **⬇ Export** renders config-driven Markdown/HTML downloads
> (`harness/export/`, `configs/export/default.yaml`, subclass-extensible registry; the HTML
> is self-contained with two-way span↔reference highlighting). Retrieval nodes now carry
> full document provenance (title/topic_path/committee/reference_number/source_type +
> a derived `category` from `harness/retrieval/doc_categories.py`), and the deterministic
> `doc_type_priority` postprocessor lets a recipe prefer e.g. guidelines over EPARs — the
> knob the SME feedback will tune. *How-to: [`docs/CITATIONS.md`](docs/CITATIONS.md).*

> 🎯 **Source-category steering** (2026-07-12, this branch). Three composable,
> fully config-driven mechanisms counter EPAR dominance in retrieval (no category/topic is
> hardcoded in code): **(A)** `:Document.category` is persisted (ingest-stamped; one-off
> `scripts/backfill_doc_categories.py`) and `HierarchicalPGRetriever` supports per-call
> category **filters** (`ema_search(source_category=...)`, oversample-and-filter in Cypher)
> + per-profile **category quotas** (stratified top-k); **(B)** opt-in **`LINKS_TO`
> expansion** (`retrieval.graph.expand`) follows link edges from vector hits and appends
> best-matching chunks of linked docs (additive, `retrieval_origin="link_expansion"`) —
> the previously-declared-but-unimplemented graph walk now exists; **(C)** a **routing
> table** (`harness/configs/routing/*.yaml`, recipe key `retrieval.routing`) maps query
> keywords to category priors (prefer/filter). Precedence: explicit agent arg > routing >
> profile defaults; expansion is always additive. All OFF by default (`neo4j_hier`
> unchanged); the `neo4j_steered` profile + `steered_agent` recipe enable the full stack.
> *See [`docs/RETRIEVAL.md`](docs/RETRIEVAL.md) §7.*

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 📋 **First action of every session: read [`BACKLOG.md`](BACKLOG.md)** — the single
> ranked queue of open work — and say what is at the top of `Now` before planning
> anything. Maintain it as work happens (rules + the 3-item cap: ["Open work"](#open-work--read-backlogmd-at-session-start) below).

## What this project is

A Q&A benchmark and reference RAG implementations built from European Medicines Agency (EMA) human-regulatory content. Three separable deliverables:
- `corpus/corpus.jsonl` — normalized Q&A pairs mined from EMA HTML accordions and PDFs
- `benchmark/benchmark.jsonl` — ~30–50 stratified evaluation questions with gold answers (T1–T4 question types)
- `harness/` — MIRAGE-style evaluation pipeline with LLM judges

See `project_roadmap/ROADMAP.md` for the full phase-by-phase plan. See `project_roadmap/GLOSSARY.md` for regulatory and NLP terminology — consult it before guessing at pharma acronyms. Critical: **"AI" means Acceptable Intake (a toxicology limit in ng/day), not Artificial Intelligence**, in EMA Q&A documents.

## Key decisions already made

Read `DECISIONS.md` before planning any implementation. Short summary of the ones most likely to affect new code:

- **Retrieval framework:** LlamaIndex — hierarchical **`PropertyGraphIndex` on Neo4j** (the former pgvector + FAISS paths were deleted in LIR-012). See `docs/RETRIEVAL.md`.
- **Site structure is the retrieval signal.** Page→PDF/page hyperlinks become `LINKS_TO` edges and section hierarchy becomes `PARENT_OF` edges in Neo4j; the retriever walks them (small-to-big + `links_to`) when semantic search underfetches. *(Historical note: the MIGR-018..025 `link_graph`/recursive-CTE machinery was documented as shipped but **never actually built** — see `docs/RETRIEVAL.md`. Links are now extracted at ingest from `web_items.html_raw` by `harness.indexing.links`.)*
- **Tracing:** MLflow (`mlflow.llama_index.autolog()` + an explicit per-turn span) — self-hosted, set up in `app.py`; `run_ui.sh` starts the MLflow server on :5000 (sqlite-backed). *(Replaced Arize Phoenix + OpenInference on 2026-06-22.)*
- **Feedback store:** MLflow trace assessments (`mlflow.log_feedback`, the Chainlit 👍/👎) — sqlite backend (`mlflow.db`), no separate database. *(Replaced the Phoenix annotation API.)*
- **Semantic cache:** thin FAISS index over past query embeddings (`harness/index/query_cache.faiss`) — GPTCache is abandoned, do not use it
- **Learning from feedback:** runtime few-shot injection from rated trajectories — no model training in the live path. *(A DSPy bootstrap loop — teacher → judge-filter → `BootstrapFewShot` — is now **scaffolded** in `harness/eval/bootstrap.py` on the agentic branch; deferred until ≥ 50 rated examples + a rebuilt eval harness exist.)*
- **Credentials:** `~/Nextcloud/Datasets/ema_nlp/ema_nlp.env` via python-dotenv — never in the repo

Open decisions not yet made are in `OPEN_QUESTIONS.md`.

## Current project phase

**Phase 1 — corpus extraction complete.** `corpus/corpus.jsonl` has 26,251 Q&A records (17,505 HTML + 8,746 PDF). Completed: TASK-001 through TASK-007 + PDF-001–PDF-004 (65k docs in `parsed_pdfs`).

**Phase 2 — benchmark drafted.** `benchmark/benchmark.jsonl`: 45 items (20 T1 / 10 T2 / 10 T3 / 5 T4). The Phase 2.5 contamination screen (closed-book runs, `zero_shot_known` tagging) is still TODO.

**Phase 3 — partial.** Retrieval + the recipe engine are live; the recipe × benchmark eval runner exists (`scripts/run_eval.py`, per-type MLflow runs). Missing: runtime verification of the runner, closed-book baselines, the lift metric.

Full phase sequence and status table: `project_roadmap/ROADMAP.md` (reconciliation banner).

**Retrieval refactor — complete** (branch `refactor/llamaindex-retrieval-pipeline`): retrieval is LlamaIndex-first on Neo4j (`harness/indexing/`, hierarchical `PropertyGraphIndex`), built over the full corpus (79,882 docs / 5.82M leaf embeddings / 99,520 `LINKS_TO` edges). The recipe engine + chat UI consume the retriever (LIR-009/010); the old pgvector/FAISS stack is deleted (LIR-012); link extraction is main-content-scoped + typed (work unit 24, 2026-06-04). See [`docs/RETRIEVAL.md`](docs/RETRIEVAL.md) and `.claude/work/2026-05-30_20_llamaindex-retrieval-refactor/`.

## Data sources

> **Starting the data services:** `scripts/start_services.sh` brings up MongoDB (`deploy/mongo/`) and Neo4j (`deploy/neo4j/`) as Docker containers and health-checks them. *(Postgres/pgvector was removed in LIR-012 — `start_services.sh` no longer starts it.)* On this host (kernel ≥ 6.19) MongoDB **must** run via the pinned `mongo:8.0.4` container — the native package crashes (SERVER-121912). See `deploy/mongo/README.md` and `deploy/neo4j/README.md`.

- **MongoDB** `ema_scraper.web_items` — raw scraped EMA pages; HTML stored as `html_raw` (1-element list), PDFs as metadata only
- **MongoDB** `ema_scraper.parsed_pdfs` — pymupdf4llm markdown keyed by URL; built by `scripts/ingest_parsed_pdfs.py --legacy`; 65k docs; query `{error: ""}` for clean parses
- **MongoDB** `ema_scraper.parsed_documents` (MIGR-001) — canonical parser-output sink. One row per `(url, parser, parser_version)`. Populated by `corpus/parsers/*.py` CLIs. **Ingestion source for `harness.indexing.ingest`.** *(The full ~80k-doc output is indexed into Neo4j; `scripts/backfill_parsed_documents_subset.py` seeds a small verify subset for CPU iteration.)*
- **MongoDB** `ema_scraper.document_metadata` (2026-07-13) — canonical per-URL EMA labels: `doc_type` (website-data JSON export), `audience`/`site_topic` (`ema-bg-*` page badges), with per-group provenance timestamps. Written post-scrape by `scripts/enrich_document_metadata.py`; joined at ingest onto `:Document` (rebuilds keep the labels); `scripts/propagate_metadata_to_graph.py` patches an existing graph without rebuild. **`scripts/update_graph.py` is the one scraper-output→Neo4j pipeline entry point** (parse → enrich → build). See `docs/RETRIEVAL.md` §2/§6/§7.
- **`ema_scraper.link_graph` — never built.** Older docs (MIGR-018..025) describe this collection; it was never populated here. Links are extracted at ingest time from `web_items.html_raw` by `harness.indexing.links.extract_links` and become `LINKS_TO` edges in Neo4j.
- **Neo4j** (Docker, `deploy/neo4j/`) — the retrieval store: a LlamaIndex `PropertyGraphIndex` of `:Document` + `:Chunk` nodes with `HAS_CHUNK`/`PARENT_OF`/`LINKS_TO` edges and a native vector index over chunk embeddings. Built by `harness.indexing.build_index` from Mongo `parsed_documents`. This is the retrieval target; `corpus.jsonl` is benchmark-only. See `docs/RETRIEVAL.md`. *(Replaced the former Postgres+pgvector store, deleted in LIR-012.)*
- **Nextcloud**: `~/Nextcloud/Datasets/` — Scrapy cache (`ema_scraper/cache/`) + IDMP ontology RDF files
- Paths are configured in `config.py`, which loads `~/Nextcloud/Datasets/ema_nlp/ema_nlp.env` via python-dotenv
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

See **"Current project phase"** above (Phase 1 done, Phase 2 drafted, Phase 3 partial). Do not introduce work from later phases without asking. The full phase sequence and success criteria per phase are in `project_roadmap/ROADMAP.md`.

## V1 scope locks

- EMA human-regulatory content only — no FDA content, no clinical trial documents. **(2026-06-02: EPARs are now IN scope for the narrative retrieval corpus** — the ~18k EPAR assessment reports in `parsed_documents` are indexed into Neo4j. The earlier "No EPARs" lock is lifted *for retrieval*; benchmark Q&A curation scope is unchanged.)
- **Narrative corpus is in scope** (the full PDF + HTML body text, indexed into the Neo4j `PropertyGraphIndex` as `:Document`/`:Chunk` nodes). `corpus.jsonl` is the curated Q&A pair extract — used by the benchmark only; runtime retrieval is over the Neo4j chunk vector index + graph edges (see `docs/RETRIEVAL.md`).
- **Neo4j is the live retrieval store** (see the refactor banner) — the earlier "no graph infrastructure in v1" lock is superseded. A *typed ontology* seam now exists too: `harness/ontology/` (`schema.py` + `enrich.py`, `configs/ontology/ema.yaml`) maps a small entity/relation schema to a LlamaIndex `SchemaLLMPathExtractor`; running Layer-2 extraction is deferred (see [`docs/TARGET_ARCHITECTURE.md`](docs/TARGET_ARCHITECTURE.md) §4.5). Legacy IDMP RDF lightweight tagging lives in `harness/ontology/concepts.yaml`; `idmp_dabbling.py` is exploratory scratch. SPOR remains out of scope.
- No multilingual content.
- Every added complexity layer must be justified by a specific benchmark failure, not anticipation.

## Data conventions

- All data files are JSONL, one record per line
- Q&A corpus record schema is defined in `project_roadmap/ROADMAP.md` Phase 1.1
- Benchmark item schema is defined in `project_roadmap/ROADMAP.md` Phase 2.3
- LLM prompts live in files, not as string literals in code
- Each eval run config goes under `harness/configs/`; result artifacts go to `config.RESULTS_DIR` (default `~/Nextcloud/Datasets/ema_nlp/results/`, override `$EMA_RESULTS_DIR`) — Nextcloud-synced across machines, never committed. MLflow remains the system of record for eval metrics.
- Raw scraped data (large artifacts) must not be committed

## Open work — read `BACKLOG.md` at session start

**[`BACKLOG.md`](BACKLOG.md) is the single ranked queue of open work.** Read it at
the start of every session, before planning anything, and open by saying what is at
the top of `Now` (and what the user was last working on, if it is still open).
This is deliberate: plans, findings and decisions live in many files, but exactly
one file says *what is open and what is next*.

Maintain it as work happens:

- **Starting something?** It must have a row. `Now` is capped at **3** — if it is
  full, ask the user what to demote rather than silently adding a fourth.
- **Finishing something?** Delete its row and append to `.claude/HISTORY.md`, in
  the same commit as the code.
- **Discovering follow-up work?** Add a row (usually to `Next` or `Later`) with a
  link to where the detail lives — never paste the detail into the backlog.
- **Deciding an open question?** Move it out of the backlog's question table into
  `DECISIONS.md`.

Do not add new status trackers. `docs/REQUIREMENTS_REVIEW.md`, `.claude/work/`
and `.claude/HISTORY.md` are historical records, not queues.

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
