# Implementation plan — LlamaIndex-first retrieval refactor

**Branch:** `refactor/llamaindex-retrieval-pipeline` (off `main@5c3c8a8`); becomes the
working branch, merged into `main` later.
**Archive:** `archive/pre-llamaindex-refactor` (at `5c3c8a8`) preserves the full
pre-refactor state incl. the benchmark suite — created so it survives the eventual merge.

**Decisions:** Neo4j `PropertyGraphIndex` (all items) · **hierarchical chunk nodes are
the default; no flat/FAISS index** · Postgres/pgvector dropped · benchmark suite removed
completely (archived) · subset-first · YAGNI throughout.

## Goal

LlamaIndex indexes are the first-class abstraction. The runtime builds **one** index —
a hierarchical `PropertyGraphIndex` over a `Neo4jPropertyGraphStore` — and retrieves
through a LlamaIndex retriever. Which index/retriever is active is chosen by an
**environment variable** pointing at a **named config profile**. Adding another index
kind later is a registry entry + a profile file. Chat UI, tracing, and feedback are kept
and re-seamed. The benchmark suite is rebuilt later, on this clean API.

## YAGNI scope decisions

- **One index kind, extensible seam.** Only the hierarchical `property_graph` builder is
  implemented. "Quickly create additional indexes" = a small `INDEX_REGISTRY` (mirroring
  `workflows/registry.py`) + a documented "Adding an index" recipe — not pre-built kinds.
- **No flat / FAISS index** (per user). Neo4j's native vector index covers pure-vector
  needs; a separate flat store earns nothing and is dropped.
- **Hierarchy is IN, by user direction.** Multi-level chunk nodes (parent/child) +
  small-to-big retrieval are the default — the one place we favor the "node-graph
  mirrors the site" vision over minimalism, because EMA docs are long/structured and
  fragment badly under flat chunking.
- **`links-to` edges only.** Richer typed edges/concepts later.
- **Benchmark suite removed completely** (not maintained half-broken); preserved on the
  archive branch; rebuilt later. The curated **data** (`benchmark/`, `corpus.jsonl`) stays.

## What "remove the benchmark suite" verified to mean (reverse-dep checked)

| Module | Fate | Why |
|--------|------|-----|
| `run_eval.py`, `eval_retrieval.py`, `compute_lift.py`, `contamination_screen.py`, `label_session.py` | **Remove** | Eval/HITL tooling; coupled to the retrieval API or to `benchmark.jsonl`/`run_eval` config |
| `harness/judge.py` + `harness/judges/` | **Keep** | `workflows/review.py` calls `Judge.faithfulness` at chat time (crag_review/react_review) |
| `harness/rating.py` | **Keep** | `app.py` uses it for 👍/👎 Phoenix annotation |
| `query_cache.py`, `fewshot_inject.py` | **Keep** | Chat-time feedback → memory/few-shot |
| `benchmark/` data, `corpus/corpus.jsonl` | **Keep** | Curated artifacts the future suite rebuilds on (data, not "suite") |
| eval configs `ablation_*`/`baseline_*`/`workflow_*`/`diag_*`/`example_chmp_only`/`retrieval_recursive` | **Remove** | Stale `run_eval` orchestration configs |
| `models.yaml`, `parser_preference.yaml` | **Keep** | LLM/role config; ingestion parser selection |

## Config + env-var switching (minimal)

`harness/configs/index/<profile>.yaml` — `index:` block (kind, store, chunking,
embed_model, source-scope) + `retrieval:` block (strategy, k, graph hops, merge).
`EMA_INDEX_PROFILE` (default `neo4j_hier`) selects the active profile. Replaces the
deleted `EMA_RETRIEVER` switch.

## Task plan (14 tasks)

**Phase A — Clear the deck (parallel; no deps)**
- **LIR-001** Remove the benchmark/eval suite completely (table above); keep judge/rating + data.
- **LIR-002** Neo4j infra: `deploy/neo4j/` compose, `NEO4J_*` env, `start_services.sh`
  → Mongo+Neo4j (Postgres out); add `llama-index-graph-stores-neo4j`; CLAUDE.md
  refactor-in-progress note.
- **LIR-003** Index/retriever registries + `EMA_INDEX_PROFILE` loader + profile schema.
- **LIR-004** Hierarchical chunker → multi-level chunk nodes (parent/child kept), stable
  ids, full metadata, `has_chunk`.

**Phase B — Data → graph**
- **LIR-005** Link extractor → `links-to` edges (build the extractor that never existed).
  deps: LIR-003.
- **LIR-006** Ingestion: Mongo → entity + hierarchical chunk nodes + has_chunk +
  parent/child + links-to; subset scope; metadata-fidelity test. deps: LIR-003,004,005.
- **LIR-007** Build the hierarchical Neo4j `PropertyGraphIndex` (persist + Neo4j vector
  index on leaf chunks; idempotent). deps: LIR-002,006.

**Phase C — Retrieval & integration**
- **LIR-008** Hierarchical retriever (small-to-big merge + 1-hop links-to). **Starts with
  a timeboxed spike** (see Risks); register; finalize `neo4j_hier` default profile.
  deps: LIR-003,007.
- **LIR-009** Re-seam workflows to a LlamaIndex retriever/query engine; drop tuple
  `retrieve_fn` + dual `index`; metadata citations. deps: LIR-008.
- **LIR-010** Chat UI seam: `app.py` → factories + `EMA_INDEX_PROFILE`; generalize source
  cards (drop `Q:/A:`); replace `cited_qa_ids` with doc/chunk citations. deps: LIR-009.

**Phase D — Verify & delete**
- **LIR-011** Verify tracing + feedback on the subset. deps: LIR-010.
- **LIR-012** Delete the dead retrieval/PG/FAISS stack (`harness/pg/*`, `retrieve_pg.py`,
  `embed*.py`, `retrieve.py`, `pg_schema.sql`, `init_db.py`, `resolve_links.py`,
  `deploy/postgres/`, `sync_pg.sh`, `EMA_RETRIEVER`). deps: LIR-010.

**Phase E — Documentation hygiene**
- **LIR-013** Doc cleanup: rewrite `CLAUDE.md`; supersede stale `DECISIONS.md` entries
  (pgvector, FAISS, link-graph "cornerstone"/MIGR-018..025, three-layer PG) + add the new
  Neo4j decision + archive-branch pointer; delete `docs/RETRIEVAL_PG.md` → write
  `docs/RETRIEVAL.md` (incl. "Adding an index"); update `OPEN_QUESTIONS.md` / roadmap refs.
  deps: LIR-012.
- **LIR-014** Clean `.claude/HISTORY.md` + memory review (prune stale memory **only with
  user confirmation**). deps: LIR-013.

## QA strategy (light)

- Unit: profile loader + env switch; hierarchical chunker (levels/ids/metadata); link extractor.
- Integration (subset): ingestion fidelity, Neo4j index build smoke, one end-to-end
  retrieve→answer through a workflow (review workflow's judge call exercised),
  tracing/feedback smoke.
- No full-corpus or benchmark gating this phase.

## Risks

- **Hierarchical retrieval on PropertyGraphIndex is not turnkey.** `AutoMergingRetriever`
  expects parent nodes in a docstore; `PropertyGraphIndex`/Neo4j is a different subsystem.
  LIR-008 starts with a timeboxed spike to choose: (a) custom parent-merge retriever over
  PG results via parent/child edges [matches "all in Neo4j"], or (b) a parallel
  docstore-backed AutoMerging layer fused with PG traversal. This is the highest-uncertainty task.
- **Neo4j + LlamaIndex version drift** — pin versions; smoke-test early (LIR-002/007).
- **Metadata loss through the store wrapper** — explicit fidelity test (LIR-006).
- **Citation contract change** ripples into UI + workflows — handle in LIR-009/010 together.

## Critical path & parallelism

Parallel start: LIR-001, LIR-002, LIR-003, LIR-004.
Critical path: LIR-003 → 005 → 006 → 007 → 008 → 009 → 010 → (011 ∥ 012) → 013 → 014.
14 tasks, mostly 2–4 h; LIR-008 carries a spike. Old retrieval code stays until the new
path is wired (LIR-010), then deleted (LIR-012) — no long broken window.
