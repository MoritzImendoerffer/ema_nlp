# Requirements — LlamaIndex-first, config-driven retrieval pipeline

**Branch:** `refactor/llamaindex-retrieval-pipeline` (off `main@5c3c8a8`); becomes the
working branch, merged into `main` later.
**Archive:** `archive/pre-llamaindex-refactor` (at `5c3c8a8`) — preserves the full
pre-refactor state incl. the benchmark suite.
**No backwards compatibility required.**

## Goal

Rebuild retrieval so **LlamaIndex indexes are the first-class abstraction**. The runtime
builds **one** index — a **hierarchical `PropertyGraphIndex` over a
`Neo4jPropertyGraphStore`** — and retrieves through a LlamaIndex retriever. Which
index/retriever is active is chosen by an **environment variable → named config
profile**. Adding another index kind later is a registry entry + a profile file. The
benchmark suite is rebuilt **later**, on this clean API; responsibilities stay separated.

## Node / graph model (target)

Built from MongoDB (`parsed_documents` + extracted links), which exists to seed the
property-graph structure:

- **Entity node** = one web page or one PDF item (document-level).
- **Chunk node** = a split chunk; **multi-level (hierarchical)** — parent/child from
  text splitting are first-class edges (per user direction), enabling small-to-big retrieval.
- **Relations:** `has_chunk` (doc→chunk), `parent`/`child` (chunk hierarchy), and
  `links-to` (the EMA hyperlink graph) first; extensible to richer typed edges later
  without reshaping the pipeline.

## Functional requirements

| ID | Requirement |
|----|-------------|
| FR1 | A named config profile selects the **index kind + backing store** and builds/persists it via one entry point `build_index(profile)`. v1 ships one kind: hierarchical `property_graph` on Neo4j. |
| FR2 | A config field selects the **retriever strategy** over a built index via `build_retriever(profile, index)` returning a LlamaIndex `BaseRetriever`. v1 ships the hierarchical small-to-big + `links-to` traversal retriever. |
| FR3 | The active profile is chosen by the **`EMA_INDEX_PROFILE` env var** (default `neo4j_hier`); profiles live in `harness/configs/index/<name>.yaml`. Replaces the old `EMA_RETRIEVER` switch. |
| FR4 | **Adding an index is cheap:** a new kind = a builder in `INDEX_REGISTRY` + a profile file + a documented recipe — no edits to workflows/UI/tracing. (Seam, not pre-built kinds.) |
| FR5 | Indexes are built from the **narrative corpus** (Mongo `parsed_documents` + extracted links), not `corpus.jsonl`. The node model above is materialized into Neo4j. |
| FR6 | **Hierarchical chunking**: `HierarchicalNodeParser` multi-level nodes; parent/child retained (the old `chunker.py:92` leaf-only discard is removed). |
| FR7 | The **chat UI** (Chainlit, `app.py`) keeps its UX. Its retrieval seam moves to the factory + `EMA_INDEX_PROFILE`; the `Q:/A:` source-card parsing (`app.py:532`) and `cited_qa_ids` contract are generalized to narrative chunks (doc/chunk citations). |
| FR8 | **Tracing** (Phoenix + OpenInference auto-instrumentation + `WorkflowRunner` span stamping) stays intact; native LlamaIndex retriever/query-engine spans appear. |
| FR9 | **Feedback** stays: semantic query cache, runtime few-shot injection from rated trajectories, 👍/👎 → Phoenix annotation (`rating.py`). Per-question **workflow selection** preserved (registry + profiles); "different questions → different workflows" remains possible (router later). |
| FR10 | **Workflow strategies** (`simple_rag`, `crag`, `react`, `summarize_rag`, composites, `review`) are preserved but re-seamed to consume a LlamaIndex retriever/query engine instead of a tuple `retrieve_fn`. The `review` workflow keeps using `harness/judge.py`. |
| FR11 | **Neo4j infra:** add `llama-index-graph-stores-neo4j`; `deploy/neo4j/` compose; `NEO4J_URI/USER/PASSWORD` in `~/.myenvs/ema_nlp.env`; `scripts/start_services.sh` → **Mongo + Neo4j** (Postgres removed); Neo4j ≥ 5.x (native vector index). |

## Non-functional requirements

- **Config-first + env-selected:** index/store/chunker/retriever declared in profile YAML; `EMA_INDEX_PROFILE` selects the active one. Vocabulary inspired by the old `retrieval_recursive.yaml`.
- **Metadata fidelity:** committee / topic_path / source_url / reference_number / page survive ingestion into node metadata (regression-test it — the LangChain bridge was removed for stripping metadata; store wrappers can too).
- **Swappable backends via LlamaIndex interfaces** so a change is config, not a rewrite.
- **Idempotent re-index** (stable node ids; no duplicate nodes/edges on rebuild).

## RESOLVED decisions (2026-05-30)

- **R1 — `Neo4jPropertyGraphStore` + `PropertyGraphIndex`**, holding **all** items; serves
  vector retrieval via Neo4j's native vector index (no separate vector store). Same store
  for subset → full (R3 is an ingestion knob, not a store change).
- **R2 — Drop Postgres/pgvector entirely** (`harness/pg/*`, `retrieve_pg.py`, `embed_pg.py`,
  CTE traversal, `pg_schema.sql`, `init_db.py`, `resolve_links.py`, `deploy/postgres/`,
  `EMA_RETRIEVER`, `PG_DSN*`, PG tests, `scripts/sync_pg.sh`). Mongo sync stays.
- **R3 — Subset-first.** Ingestion scope filter (committee / topic_path / url / doc cap).
- **R4 — Hierarchical PropertyGraphIndex is the default and ONLY index kind.** No
  flat/FAISS index (per user). The factory keeps the seam for adding kinds later.
- **R5 — Benchmark suite removed completely** from this branch (preserved on
  `archive/pre-llamaindex-refactor`); rebuilt later. Reverse-dep-verified split below.

### What "remove the benchmark suite" means (reverse-dep verified)

| | Items |
|---|---|
| **Remove** | `harness/{run_eval,eval_retrieval,compute_lift,contamination_screen,label_session}.py` + their tests; eval configs `ablation_*`/`baseline_*`/`workflow_*`/`diag_*`/`example_chmp_only`/`retrieval_recursive` |
| **Keep — runtime, NOT benchmark** | `harness/judge.py` + `harness/judges/` (review workflow), `harness/rating.py` (chat 👍/👎), `query_cache.py`, `fewshot_inject.py`, `models.yaml`, `parser_preference.yaml` |
| **Keep — curated data** | `benchmark/` (benchmark.jsonl, SCHEMA.md, validate_benchmark.py, candidates), `corpus/corpus.jsonl` |

## Keep / Replace / Delete inventory (code)

**KEEP (adapt at the seam):** `app.py`; Phoenix tracing + `WorkflowRunner` stamping;
`harness/query_cache.py`, `harness/fewshot_inject.py`, `harness/rating.py`,
`harness/judge.py` + `harness/judges/`; `harness/llms.py` + `models.yaml` +
`harness/providers.py`; `harness/workflows/*`; `corpus/parsers/*` +
`corpus/sources/parsed_documents.py` + Mongo `parsed_documents`/link data.

**REPLACE (rebuild LlamaIndex-first):** `harness/embed.py`, `harness/embed_pg.py`,
`harness/embed_hierarchical.py` → **index factory**; `harness/retrieve.py`,
`harness/retrieve_pg.py` → **retriever factory**; `corpus/ingestion/chunker.py` →
hierarchical chunker (keep parents; emit relationships).

**DELETE (no back-compat):** the Postgres stack (R2); the benchmark suite (R5);
the `EMA_RETRIEVER` switch; tuple `RetrievalResult` plumbing once workflows take
LlamaIndex retrievers.

## Acceptance criteria

1. `EMA_INDEX_PROFILE` selects a profile; `build_index` then `build_retriever` produce a
   working LlamaIndex retriever over the hierarchical Neo4j PropertyGraphIndex.
2. Adding a second index kind is demonstrably a registry entry + profile file (recipe documented).
3. Chat UI answers end-to-end on the Neo4j index, sources shown, tracing recorded, 👍/👎 persisted; the `review` workflow's judge call works.
4. Node model verified in Neo4j: entity + hierarchical chunk nodes + has_chunk + parent/child + links-to; metadata retains committee/topic/url/page.
5. No import of the deleted retrieval/PG stack or removed benchmark modules on the runtime path.

## Risks

- **Hierarchical retrieval on PropertyGraphIndex is not turnkey** (highest uncertainty):
  `AutoMergingRetriever` expects parents in a docstore; PropertyGraphIndex/Neo4j is a
  different subsystem. LIR-008 starts with a timeboxed spike to choose a custom
  parent-merge over PG results vs a docstore-backed AutoMerging layer fused with traversal.
- **Neo4j + LlamaIndex version drift** — pin and smoke-test early.
- **Metadata stripping** through the store wrapper — fidelity test (LIR-006).
- **Citation contract:** narrative chunks have no `qa_id`; UI + workflows need a doc/chunk
  citation scheme (LIR-009/010).
