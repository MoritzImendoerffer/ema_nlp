# Architecture and scope decisions

Running log of decisions that are not obvious from the code. Each entry has a rationale and a link to the fuller exploration if one exists. Read this after a break to reconstruct why things are the way they are.

See `OPEN_QUESTIONS.md` for decisions not yet made.

---

## Scope

### EMA human-regulatory Q&As only — v1 scope lock
**Decided:** project start  
**What:** Corpus and benchmark cover only EMA human-regulatory Q&A documents (HTML accordions and numbered-section PDFs). No FDA content, no biomedical literature, no clinical trial documents, no multilingual content.  
**Why:** Keeps the corpus extractable in one week of evenings, the benchmark curated by one SME, and the ablations controlled. Complexity is introduced only when a benchmark failure demands it.  
**Deferred to v2+:** multilingual (OPUS EMEA is a hook), biomedical/clinical questions beyond regulatory scope.

**Amended 2026-05-30 / 2026-06-02 (retrieval refactor):** EPARs are **now in scope for the narrative retrieval corpus.** The ~18k EPAR public-assessment-report PDFs already in `parsed_documents` are indexed into the Neo4j `PropertyGraphIndex` (work unit 21). The original "No EPARs" lock applied to the v1 *benchmark Q&A* curation, which is unchanged; this amendment only brings EPARs into the retrieval index. (User decision, 2026-06-02.)

### No ontology or graph infrastructure in v1
**Decided:** project start; refined 2026-05-15  
**What:** IDMP/SPOR ontology and Neo4j are out of scope for v1. The IDMP RDF files are used only for lightweight concept tagging on LlamaIndex nodes (TASK-016.5) — simple string matching against concept labels, stored as node metadata for metadata filtering. No graph DB, no entity-linking, no SPARQL.  
**Why:** The `cross_refs` field in the corpus schema already encodes the most useful graph structure (Q&A cross-references). LlamaIndex `NodeRelationship` captures these without Neo4j. Full graph-RAG is only justified if Ablation B shows the cross-ref traversal tool is insufficient on T3 questions.  
**Deferred to v2+:** PropertyGraphIndex, Neo4j, SPARQL queries over IDMP.  
**Ref:** [`project_roadmap/ROADMAP.md`](project_roadmap/ROADMAP.md) — "What's explicitly deferred to v2+"

---

## Retrieval framework

### LlamaIndex-first retrieval: hierarchical PropertyGraphIndex on Neo4j
**Decided:** 2026-05-30 (branch `refactor/llamaindex-retrieval-pipeline`, work unit `2026-05-30_20_llamaindex-retrieval-refactor`)
**What:** Retrieval is rebuilt LlamaIndex-first. The single store is a hierarchical LlamaIndex `PropertyGraphIndex` backed by `Neo4jPropertyGraphStore`: `:Document` + `:Chunk` nodes; `HAS_CHUNK` / `PARENT_OF` / `LINKS_TO` edges; Neo4j's native vector index over chunk embeddings. A custom `HierarchicalPGRetriever` does vector hit → small-to-big parent merge + `links_to` expansion in one Cypher. Active index/retriever is chosen by `EMA_INDEX_PROFILE` → `harness/configs/index/*.yaml`; new kinds register through `harness.indexing`'s registries. Built by `harness.indexing.build_index` from Mongo `parsed_documents`.
**Why:** pgvector was a second store with hand-rolled SQL + a recursive-CTE traversal re-implementing a graph store; FAISS-over-`corpus.jsonl` indexed the curated Q&A surface (not the narrative body) and leaked gold answers. Neo4j holds graph + vectors in one store and makes site structure (links, hierarchy) first-class retrieval edges.
**Supersedes:** the four retrieval decisions below — *FAISS as the vector store backend*, *Postgres + pgvector as the narrative-corpus retrieval backend*, *Three-layer separation (… → PG)*, and *Link graph as retrieval cornerstone* — retained below for history, no longer current.
**Status (2026-06-04, shipped):** offline pipeline (`harness/indexing/`) built; the full graph indexed (79,882 docs / 5.82M leaf embeddings / 99,520 `LINKS_TO`); workflow + chat-UI re-seam (LIR-009/010) and old-stack deletion (LIR-012) **complete** — the pgvector/FAISS stack is gone.
**Ref:** [`docs/RETRIEVAL.md`](docs/RETRIEVAL.md), [`.claude/work/2026-05-30_20_llamaindex-retrieval-refactor/`](.claude/work/2026-05-30_20_llamaindex-retrieval-refactor/)

### Link extraction: main-content-scoped, BCL-component-aware, typed `LINKS_TO` edges
**Decided + shipped:** 2026-06-04 (work unit `2026-06-04_24_link-extraction-upgrade`; spec `docs/RETRIEVAL_TRACKS.md` §0.8)
**What:** `harness/indexing/links.py` was rewritten by **porting** (not importing) the proven extractor from the sibling `ema_scraper` repo (`parsers/ema_parser.py`, `EmaPageParser`). Extraction is now scoped to `<main class="main-content-wrapper">` (skipping `bcl-inpage-navigation` / `breadcrumb` / `dropdown-menu` / `<nav>` / `script`…), walks the content **recursively** (so deeply-nested + accordion-body links are found) with an `id()`-based processed-set, and is **BCL-component aware**. `ExtractedLink` gained `link_context` (`file_component` | `card_or_listing` | `inline` | `other`) and `document_type` (from `data-ema-document-type` on `.bcl-file` cards); existing `kind`/`anchor` + URL normalization are unchanged (parser switched to `html.parser` for parity with the scraper). `LINKS_TO` is a **single relationship label carrying `{kind, link_context, document_type, anchor}` as properties** (not typed labels), stamped by both `to_graph` (IR path) and the live `_links_pass`/`_merge_links_batch`. Track B filters expansion via new `GraphRetrievalConfig.link_contexts` + `document_types` profile fields (explicit fields — **supersedes** the earlier "reinterpret `edge_types`" idea). A `reset_links` path (`build --links-only --reset-links`) deletes + re-MERGEs `LINKS_TO` via `CALL { … } IN TRANSACTIONS` **without touching chunks/embeddings**.
**Why:** the old whole-page, URL-shape-only extractor turned global header/footer/mega-menu chrome into edges — **74 chrome targets absorbed 94.4 % of the 1.72 M `LINKS_TO` edges** (each global-nav target at in-degree 21,956), drowning the load-bearing HTML→PDF "card" links (only 3.4 % of edges). Main-content scoping removes the chrome **structurally, at the source**, so Track B's retriever walks a clean, typed graph instead of needing a degree-cap workaround.
**Result (rebuild executed 2026-06-04):** `LINKS_TO` **1,721,581 → 99,520** (−94.2 %), chunks/`HAS_CHUNK`/`PARENT_OF` unchanged; **0** chrome targets (max in-degree 21,956 → 567); HTML→PDF card share **3.4 % → 58.3 %**; `file_component` 54,347 (all with `document_type`) / `inline` 35,673 / `other` 7,865 / `card_or_listing` 1,635.
**Not chosen:** importing `ema_scraper` across repos (porting keeps BCL knowledge in this repo, parser-agnostic); typed relationship labels per context (premature at 10⁵ edges; properties keep the schema simple + composable); re-adding edge `kind` only (the chrome problem is *region*, not URL shape — scoping is the real fix).
**Ref:** [`docs/RETRIEVAL_TRACKS.md`](docs/RETRIEVAL_TRACKS.md) §0.8, [`.claude/work/2026-06-04_24_link-extraction-upgrade/`](.claude/work/2026-06-04_24_link-extraction-upgrade/)

### LlamaIndex as the RAG framework
**Decided:** 2026-05-15  
> *Detail drift (2026-07-05): the core decision stands. Of the named backends, only `faiss-cpu` remains a direct dep (semantic query cache); `rank-bm25` was dropped 2026-07-04, and OpenInference went with Phoenix (MLflow autolog now traces at the LlamaIndex level).*

**What:** LlamaIndex is the retrieval and agent framework. Raw FAISS, sentence-transformers, and rank-bm25 are used as backends via LlamaIndex wrappers — they stay in `pyproject.toml` as direct deps.  
**Why:** `DocumentSummaryIndex` directly implements the document-tree-with-summaries approach (PageIndex model) — each EMA source document gets a cheap summary node; Q&A pairs are leaf nodes. `NodeRelationship` models `cross_refs` without a graph DB. `ReActAgent` is the agent architecture for Ablation B. OpenInference instrumentation works at the LlamaIndex level so tracing is model-agnostic.  
**Not chosen as the retrieval engine:** LangChain/LangGraph — better for prompt-chain-centric work; LlamaIndex is the superior choice for structured document retrieval and docstore indexing. LangChain/LangGraph were trialled for the orchestration layer and subsequently removed in favour of LlamaIndex Workflows (see decision below).  
**Ref:** [`.claude/work/2026-05-15_04_agentic-memory-architecture/exploration.md`](.claude/work/2026-05-15_04_agentic-memory-architecture/exploration.md)

### FAISS as the vector store backend (v1) — superseded for narrative-corpus runtime
**Decided:** project start (confirmed 2026-05-15); **superseded 2026-05-26 by Postgres + pgvector below**, for the runtime retrieval path  
**What (original):** FAISS flat index for both the document index and the query cache index. In-memory-friendly, no server required, persisted to `harness/index/`.  
**Why (original):** Sufficient for the Q&A corpus size (~26k records). The Qdrant migration path was the obvious next step if scale or latency became a problem.  
**Status (2026-05-26):**
- **Narrative corpus (PDF + HTML body text) — moved to Postgres + pgvector** (NARR-001..028). This is the runtime retrieval target; `corpus.jsonl` + FAISS no longer cover the actual chunk surface used by the agent.
- **Q&A FAISS index over `corpus.jsonl`** — retained as a back-compat opt-out via `EMA_RETRIEVER=faiss`. Not the default. Used for parity smoke tests; not on the critical path for new work.
- **Query cache** (`harness/index/query_cache.faiss`) — **still FAISS, unchanged.** It indexes past *query embeddings* for semantic similarity to surface rated past trajectories; it is not a document store, so the pg migration does not apply.

**Ref:** see the new "Postgres + pgvector as the narrative-corpus retrieval backend" decision below.

### Postgres + pgvector as the narrative-corpus retrieval backend
> ⚠ **SUPERSEDED 2026-05-30** by *LlamaIndex-first retrieval: hierarchical PropertyGraphIndex on Neo4j* (above). Postgres/pgvector is being removed. Retained for history.

**Decided:** 2026-05-25 (planning); shipped 2026-05-26 (NARR-001..028, default flipped in NARR-028)  
**What:** Postgres 16 + pgvector 0.8.2 is the runtime retrieval store. Schema: `documents` (one row per source URL), `chunks` (HNSW dense index over `embedding vector(1024)`, BM25 via generated `text_tsv` + GIN), `links` (per-chunk hyperlinks, EMA reference codes, and resolved `tgt_doc_id`s). Provisioned via `deploy/postgres/docker-compose.yml` (image `pgvector/pgvector:pg16`); schema applied by `python scripts/init_db.py`; populated by `python -m harness.embed_pg` from MongoDB. Retrieval surface lives in `harness/retrieve_pg.py` (`retrieve_dense_pg`, `retrieve_bm25_pg`, `retrieve_hybrid_pg`, `retrieve_with_config_pg`, `build_retrieve_fn_pg`) with the same `RetrievalResult = (id, score, metadata)` tuple shape as the FAISS path — workflows are unaware of the backend. Embeddings use the same `BAAI/bge-large-en-v1.5` model (1024-d) as the FAISS path, on local CUDA (3090).  
**Why:**
- The `corpus.jsonl` Q&A pairs are a tiny fraction of the actual content; the agent needs the **full narrative body text** (chapter prose, headings, tables) for T2 scoping and T4 synthesis questions, not just the curated Q/A surface.
- Postgres gives BM25, dense, and a relational `links` table in one store, queried with one round-trip — no separate FAISS + BM25 + graph layer to keep in sync.
- HNSW on pgvector ≥ 0.5 matches FAISS HNSW latency at the scales relevant here (validated NARR-011: ~6 h full-corpus ingest, 14–18 GB DB total, dense top-10 well under 100 ms on the seeded slice).
- Idempotent re-ingest is trivial (`ON CONFLICT … DO UPDATE`), so corpus rebuilds don't require throwing away embeddings.
- Tracing parity: `WorkflowRunner._stamp_span` stamps `ema.retrieval.backend = 'pgvector'\|'faiss'` so Phoenix runs can filter by backend without changing the workflow code.

**Switch contract:**
- `EMA_RETRIEVER=pgvector` (default since NARR-028) — `app.py` and `harness/run_eval.py` skip `build_index` (no FAISS load), build a `RetrievalConfigPG`-backed `retrieve_fn`, and embed via `Settings.embed_model`.
- `EMA_RETRIEVER=faiss` — legacy path; unchanged. Use only for parity smoke tests against `corpus.jsonl`.
- `PG_DSN` (default `postgresql://ema_nlp:ema_nlp@localhost:5432/ema_nlp`) and an optional `PG_DSN_TEST` for the integration suite.

**Not chosen:**
- *Qdrant / Chroma / Weaviate* — Postgres already runs locally and gives BM25 + relational joins for free; adding a fourth database server is unjustified at this scale.
- *Keeping FAISS and grafting BM25/links on top* — would have duplicated state across three stores and broken transactional re-ingest.

**Open follow-ups:** none load-bearing. Reranker (A3) and query-expansion (A1) wrappers still sit outside the retriever and apply to both backends via `build_retrieve_fn{,_pg}`.  
**Ref:** `docs/RETRIEVAL.md` (was `docs/RETRIEVAL_PG.md`, removed), [`.claude/work/2026-05-25_16_pgvector-narrative-corpus/`](.claude/work/2026-05-25_16_pgvector-narrative-corpus/) (28-task work unit), `corpus/pg_schema.sql`, `harness/retrieve_pg.py` (both deleted in LIR-012)

### BGE-large-en as the embedding model (v1)
**Decided:** project start  
**What:** `BAAI/bge-large-en` via `llama-index-embeddings-huggingface` for both document and query embeddings. Same model used for the query cache similarity search so the embedding spaces are aligned.  
**Why:** Strong English retrieval performance, freely available, runs on CPU. Avoids an API embedding dependency.  
**Note:** Not yet benchmarked against alternatives — document the choice and revisit if retrieval metrics in Phase 3 are disappointing.

### LlamaIndex Workflows for all orchestration (supersedes LangChain + LangGraph)
> **Superseded 2026-06-25** by *Single-engine agentic RAG (recipe engine)* below. The bespoke
> `Workflow` engine (`harness/workflows/*`, `WorkflowRunner`, `get_workflow`) was deleted;
> LlamaIndex itself stays (the orchestrator is now a `FunctionAgent`).

**Decided:** 2026-05-22  
**What:** LlamaIndex Workflows (`harness/workflows/`) handle all prompt chains, agent loops, and pipeline orchestration. LangChain, LangGraph, and LangSmith are removed from the stack entirely.  
**Why:** The LangChain bridge (`EMARetriever`) stripped node metadata, required global LlamaIndex state to be configured before any LangGraph node ran retrieval, and forced two divergent ReAct implementations. Using LlamaIndex Workflows end-to-end eliminates the bridge, keeps node metadata intact throughout the pipeline, and reduces dependency count.  
**Architecture:** `harness/workflows/registry.py` provides a single `get_workflow(name, index, llm)` entry point for 8 registered strategies — the 7 workflow strategies plus the additive `agent` strategy (the agentic `FunctionAgent`, registered 2026-06-22 via `harness/agents/workflow_adapter.py`; see [`docs/TARGET_ARCHITECTURE.md`](docs/TARGET_ARCHITECTURE.md)). Every strategy is a typed, event-driven `Workflow` (or, for `agent`, a `FunctionAgent` wrapped to the same `invoke`/`ainvoke` contract). All strategies expose `.invoke()` and `.ainvoke()` via `WorkflowRunner`.  
**Not chosen:** Using LangGraph for orchestration — the impedance mismatch at the LlamaIndex/LangChain boundary outweighed the benefits of LangGraph's state machine semantics for this retrieval-centric project.  
**Ref:** [`.claude/work/2026-05-22_10_llamaindex-langgraph-assessment/`](.claude/work/2026-05-22_10_llamaindex-langgraph-assessment/)

### Single-engine agentic RAG (recipe engine) supersedes the Workflow engine
**Decided:** 2026-06-25  
**What:** There is now **one** orchestration engine — a LlamaIndex `FunctionAgent` — configured by a **recipe** (`harness/configs/recipes/*.yaml` + `$EMA_CONFIG_DIR`). The legacy Workflow engine (`harness/workflows/*`: `simple_rag`/`crag`/`summarize_rag`/`react_native`/composites, `WorkflowRunner`, `get_workflow`, the `prompt_strategy` axis) was **deleted**. RAG techniques are now **tools + prompt instructions**, not workflow classes: Naive RAG → `ema_search`; CRAG → the `corrective_search` tool (the bounded grade/rewrite loop, single-sourced in `harness/retrieval/corrective.py`); ReAct → the agent's native tool loop. `build_recipe(recipe, index)` is the single composition path.  
**Why:** Agentic RAG is the first-class citizen — naive RAG is a simple tool call and CRAG is a *configuration* of the agent, not a parallel engine. The prior "additive agent alongside the workflow zoo" was two engines + a dual mode-selector (ChatProfiles × workflow×prompt) modelling the same choice twice. Collapsing to one engine removes the duplication, makes techniques composable (add a tool + a recipe — no new orchestration code), and lets one recipe dropdown drive everything with the resolved config stamped honestly on each MLflow trace. Deterministic loop bounds (CRAG `max_cycles`) live inside the tool, so the agent doesn't improvise control flow; adherence is checked retrospectively (trace inspection + the optional inline judge).  
**Still LlamaIndex:** the `FunctionAgent`, retriever, and tools are all LlamaIndex — only the bespoke `Workflow` *engine* was retired, not the framework.  
**Ref:** [`docs/RECIPES.md`](docs/RECIPES.md), [`docs/RAG_TECHNIQUES.md`](docs/RAG_TECHNIQUES.md). Supersedes "LlamaIndex Workflows for all orchestration" + "Native ReAct workflow" above and "Workflow registry collapsed: prompt_strategy as YAML field" below.

### Reviewer-in-the-loop: soft recommendation, never a hard gate (R1-Q3)
**Decided:** 2026-07-05 (owner answer to REQUIREMENTS_REVIEW R1-Q3, 2026-07-02; implemented as F18)  
**What:** The post-generation reviewer is **advisory**: `JudgePolicy` gained `threshold` (1–5 judge scale) and `on_fail: annotate`. When the inline judge scores below the threshold — or cannot produce a score — the answer still ships, with a visible ⚠️ caution note appended and the verdict stamped on the turn trace (`ema.judge.threshold` / `ema.judge.passed`). The agent's structured `confidence` is also shown in the final message ("certainty of the statements should be visible"). The judging model is bound per recipe via `judge.model_role` (e.g. the `reviewer` role in models.yaml).  
**Why:** The owner picked the recommendation flavor over a hard block/retry gate ("a recommendation seems to be easier to implement; in the final answer, certainty of the statements should be visible"). A hard `on_fail: retry|block` seam can be added later behind the same config surface — naming it today raises a config error rather than silently doing nothing.  
**Not chosen (for now):** hard gating (block/retry below threshold) — deferred until a benchmark failure demands it; a `review_answer` *tool* — a tool cannot intercept the agent's final output, so the adapter-level seam is the one that can actually gate.  
**Ref:** [`docs/RECIPES.md`](docs/RECIPES.md), `harness/eval/inline_judge.py:review_verdict`, [`docs/REQUIREMENTS_REVIEW.md`](docs/REQUIREMENTS_REVIEW.md) (F18/R1-Q3)

### Role/model separation in models.yaml
**Decided:** 2026-05-23  
**What:** `harness/configs/models.yaml` is restructured into two top-level sections:
- `models:` — model definitions keyed by a stable name (e.g. `claude_haiku`, `claude_opus`, `olmo_32b`, `local_qwen32`). Each entry has `provider`, `model_id`, `max_tokens`, `temperature`, and optionally `api_base` + `api_key_env` for `openai_compatible` servers.
- `roles:` — maps functional roles (`agent`, `grader`, `rewriter`, `reranker`, `judge`, `reviewer`) to model names. Change a role here to swap the model everywhere it's used.

`get_llm(role_name)` (in `harness/llms.py`) replaces `get_llm(tier_id)`. `load_model_for_role(role_name)` replaces `load_tier(tier_id)`. The constants `TIER_MID`, `TIER_FRONTIER`, `TIER_OLMO`, `TierId` are removed from hot paths.  
**Why:** The old `tier_id` conflated two concerns: which model to use AND what it's used for. Swapping the grader to a local model for offline runs required touching every call site. Roles decouple these: `roles.grader: local_qwen32` swaps only the grader with no code change.  
**Default role mapping:** grader/rewriter/reranker → `claude_haiku`; agent/judge/reviewer → `claude_opus`. Note: `agent` was initially Haiku but promoted to Opus after HITL-004a diagnosis showed Haiku skips tool calls in the ReAct loop (see `.claude/work/2026-05-24_12_hitl-pipeline-gaps/react_diagnosis.md`).

### Native ReAct workflow (`react_native.py`) as the default `react` strategy
> **Superseded 2026-06-25** — `react_native.py` was deleted with the Workflow engine. ReAct is
> now the `FunctionAgent`'s native tool loop (the `react_agentic` recipe); per-step visibility
> comes from MLflow autolog rather than hand-written `@step` spans.

**Decided:** 2026-05-23  
**What:** The registry key `react` now points to `ReActNativeWorkflow` (`harness/workflows/react_native.py`), a hand-written LlamaIndex `Workflow` where every agent action is a separate `@step`. The legacy `FunctionAgent`/`AgentWorkflow` implementation (`react.py`) was deleted (HITL-001, 2026-05-24).  
**Why:** `FunctionAgent`/`AgentWorkflow` wraps the entire ReAct loop in a single span — Phoenix can label the final answer but not individual tool calls or thoughts. `ReActNativeWorkflow` splits each think/act/observe into its own `@step`, so Phoenix traces show per-step spans that the HITL annotation system can label independently (`step_quality: good/suboptimal/wrong`).  
**Architecture:** Events: `ThoughtEvent`, `ActionEvent`, `ObservationEvent`, `FinishEvent` (all in `events.py`). Steps: `think` (StartEvent|ObservationEvent → ThoughtEvent|FinishEvent), `act` (ThoughtEvent → ActionEvent), `observe` (ActionEvent → ObservationEvent), `finish` (FinishEvent → StopEvent). Max iterations guard defaults to 5. Same 4 tools as `react_legacy`: `ema_search`, `follow_cross_refs`, `filter_by_topic`, `get_qa_by_id`.  
**Not chosen:** Keeping `FunctionAgent` for tracing — it does not expose per-step events to Phoenix.

### `orchestration:` block as the answer-generation schema in eval configs
**Decided:** 2026-05-23  
> **Superseded 2026-06-25** by the single-engine recipe model: `get_workflow()` / `harness/workflows/registry.py` were deleted with the Workflow engine; orchestration is now a recipe (`harness/configs/recipes/*.yaml`), and eval runs recipes via `harness/eval/runner.py`.

**What:** Eval YAML configs use a top-level `orchestration:` block (with `strategy` and `tier_id` sub-keys) to specify which workflow strategy generates answers. The old `answer_generation:` block (with `enabled`, `strategy`, `tier_id`) is removed.  
**Schema:**
```yaml
orchestration:
  strategy: simple_rag_zero   # any key from harness/workflows/registry.py
  tier_id: mid                # model tier — removed entirely in REFACT-007 (role-based)
```
Configs *without* an `orchestration:` block skip answer generation silently (used by retrieval-only baseline runs A0 and A0+).  
**Why:** The old `answer_generation:` block called `harness.answer_gen.generate_answer()` directly, bypassing the LlamaIndex workflow layer. The new schema routes through `get_workflow()` in the registry, so every strategy gets Phoenix tracing, event-driven steps, and the same `invoke()` interface used everywhere else. `harness/answer_gen.py` is deleted.  
**Mapping from old strategies:** `zero_shot → simple_rag_zero`, `few_shot → simple_rag_few`, `cot_self → simple_rag_cot`.

---

## Observability and tracing

### MLflow replaces Arize Phoenix for tracing + feedback (live app)
**Decided:** 2026-06-22 (shipped)  
**What:** The live Chainlit app, the workflow stack, and the in-app agent are all traced by **MLflow** — `mlflow.llama_index.autolog()` plus an explicit per-turn root span (`harness.obs.tracing.traced`) that carries the resolved `ema.*` config. 👍/👎 feedback is an **MLflow trace assessment** (`mlflow.log_feedback`, name `user_rating`). `run_ui.sh` starts an `mlflow server` on :5000 backed by **sqlite** (`mlflow.db`); the app logs over HTTP and the same server serves the UI. **Arize Phoenix + OpenInference were fully removed:** the deps (`arize-phoenix`, `openinference-*`), the `phoenix.otel` registration, the annotation feedback path, and the Phoenix CLI tools (`harness/rating.py`, `harness/hitl/`) are gone; `harness/export_traces.py` now harvests rated traces from MLflow `search_traces`.  
**Why:** One tool for traces + eval + judges + judge **alignment** (the reward signal the bootstrap loop needs — no Phoenix equivalent). The agentic layer already used MLflow for run-recording/judges; unifying the live app on it removes the two-backend split. **Backend = sqlite** because the MLflow file store cannot persist trace assessments (verified: `log_feedback` 404s on the file store, succeeds on sqlite/server).  
**Supersedes:** the two entries below (*Arize Phoenix + OpenInference*, *Phoenix annotations as the feedback store*).  
**Ref:** `app.py`, `harness/obs/tracing.py`, `run_ui.sh`, [`docs/TARGET_ARCHITECTURE.md`](docs/TARGET_ARCHITECTURE.md) §4.7.

---

### Arize Phoenix + OpenInference for model-agnostic tracing
> ⚠ **SUPERSEDED 2026-06-22** by *MLflow replaces Arize Phoenix for tracing + feedback* above. Retained for history.

**Decided:** 2026-05-15  
**What:** Arize Phoenix (self-hosted, open source) captures every retrieval step, reranking call, and LLM call as an inspectable span tree. Instrumented via `LlamaIndexInstrumentor` at the framework level — works regardless of which LLM is used (Claude, GPT, OLMo 3, local models). Per-run trace export (`traces.jsonl`) is saved alongside config and results in `results/<run_id>/`.  
**Why:** OlmoTrace (the other tracing tool mentioned in the roadmap) is OLMo-specific. Phoenix covers all models. Self-hosted means no cloud account, traces stay local.  
**Ref:** [`project_roadmap/LEAKAGE.md`](project_roadmap/LEAKAGE.md) §7.5 for OlmoTrace context; [`.claude/work/2026-05-15_04_agentic-memory-architecture/exploration.md`](.claude/work/2026-05-15_04_agentic-memory-architecture/exploration.md)

---

## Feedback and online learning

### Phoenix annotations as the feedback store (not SQLite)
> ⚠ **SUPERSEDED 2026-06-22** by *MLflow replaces Arize Phoenix for tracing + feedback* (above). Feedback is now an MLflow trace assessment. Retained for history.

**Decided:** 2026-05-15 (revised from initial SQLite design)  
**What:** User ratings (1–5 stars, optional per-step labels) are posted to Phoenix via its annotation API and attached to the relevant trace span. No separate database. Phoenix's Postgres instance (part of its Docker deployment) is the store.  
**Why:** Phoenix is already running for tracing. Its annotation API accepts exactly the data model needed. A custom SQLite store would duplicate infrastructure already present. GPTCache (the obvious semantic caching library) is effectively abandoned since late 2023 with a broken LlamaIndex integration.  
**Ref:** [`.claude/work/2026-05-15_05_rl-feedback-cache/exploration.md`](.claude/work/2026-05-15_05_rl-feedback-cache/exploration.md)

### Thin FAISS query cache for semantic similarity (not GPTCache)
**Decided:** 2026-05-15  
**What:** A secondary FAISS index over embeddings of past queries, persisted to `harness/index/query_cache.faiss` with a JSON sidecar. Used to surface similar past questions to the user before running the pipeline. The user always confirms before any cached answer is used.  
**Why:** GPTCache is abandoned and broken with current LlamaIndex. Building a thin FAISS index reuses the existing embedding model (same BGE-large) and adds ~60 lines of code with no new dependencies.  
**What it is not:** A silent cache. The user always sees the similar questions and explicitly chooses to use a cached result or run fresh. Benchmark evaluation always runs with `cache: false`.

### Runtime few-shot injection from rated trajectories (no model training)
**Decided:** 2026-05-15; wired 2026-05-24 (HITL-007)  
**What:** At query time, the top-k highest-rated past trajectories (rating ≥ 4/5) for similar questions are fetched from the query cache and injected into the agent's planning prompt as few-shot examples. No weights updated. All learning is in-context.  
**Why:** Standard few-shot prompting. Every injected example is traceable (its `run_id` links to an MLflow trace — originally Phoenix), satisfying the reproducibility requirement.  
**Implementation (updated 2026-07-04):** `harness/fewshot_inject.py:get_fewshot_context(query_vec, cache, k, min_rating, min_examples)` — gated per recipe by `FewshotPolicy` (`enabled`, `k`, `min_rating`, `min_examples`, default `min_examples=1`) and injected via `app.py` when the recipe enables it. Suppresses injection when fewer than `min_examples` qualifying entries exist — fails closed.

### DSPy deferred until ≥ 50 rated examples exist
**Decided:** 2026-05-15  
**What:** DSPy (`BootstrapFewShot` / `MIPROv2`) is not used yet.  
**Why:** DSPy is a batch offline compiler, not a runtime few-shot selector. It needs a labeled dataset of sufficient size (50+ for `BootstrapFewShot`, 200+ for `MIPROv2`) before the optimization run is useful. It also requires restructuring the pipeline into DSPy modules, which conflicts with the LlamaIndex architecture already decided.  
**When to add:** After the feedback system (TASK-027.5–027.9) has accumulated ≥ 50 rated interactions.

---

## Evaluation design

### Lift (open-book minus closed-book) as the headline metric
**Decided:** project start  
**What:** Every model is reported with two numbers side by side: closed-book score (no retrieval) and open-book score (full RAG). The headline metric is the difference — the lift RAG provides over memorization.  
**Why:** EMA Q&As are old, public, and almost certainly in frontier LLMs' training data. Absolute open-book scores are inflated by memorization and cannot be compared across models with different training cutoffs. Lift is contamination-robust: memorization affects both arms roughly equally, so the gap is still informative.  
**Ref:** [`project_roadmap/LEAKAGE.md`](project_roadmap/LEAKAGE.md)

### Four question types, always reported separately
**Decided:** project start  
**What:** T1 Lookup, T2 Scoping, T3 Multi-hop, T4 Synthesis. All five evaluation metrics are reported broken down by type, not aggregate only.  
**Why:** Aggregate metrics hide which retrieval strategies break which question types. The entire ablation design is built around observing per-type behavior.  
**Ref:** [`project_roadmap/ROADMAP.md`](project_roadmap/ROADMAP.md) §2.1; [`project_roadmap/ABLATIONS.md`](project_roadmap/ABLATIONS.md)

### OLMo 3 as contamination-verifiable reference model
**Decided:** project start  
**What:** OLMo 3 (Allen AI, 32B Think variant) included as the third model tier in Ablation C. Its training corpus (Dolma 3) is fully released and searchable — EMA content presence can be verified rather than guessed.  
**Why:** If ablation gain patterns hold across mid-tier, frontier, and OLMo 3, the observed effects are likely real retrieval behavior rather than memorization artifacts.  
**Ref:** [`project_roadmap/LEAKAGE.md`](project_roadmap/LEAKAGE.md) §7.5; [`project_roadmap/ABLATIONS.md`](project_roadmap/ABLATIONS.md) Ablation C

---

## Infrastructure

### Eval results on Nextcloud, not in the repo
**Decided:** 2026-05-23  
**What:** `results/` is a symlink to `~/Nextcloud/Datasets/ema_nlp/results/`. The symlink is in `.gitignore`. All `harness/configs/*.yaml` files specify `base_dir: ~/Nextcloud/Datasets/ema_nlp/results` so `run_eval.py` writes there via tilde expansion.  
**Why:** Eval runs produce JSON/JSONL/PNG artefacts that should not inflate the repo. All data lives on Nextcloud (synced between machines) while the symlink keeps the `results/` path alias working in dev.  
**Ref:** [`docs/SETUP.md`](docs/SETUP.md) §7

### Credentials in `~/.myenvs/ema_nlp.env`, never in the repo
**Decided:** 2026-05-15  
**What:** All secrets (`ANTHROPIC_API_KEY`, MongoDB sync settings) live in `~/.myenvs/ema_nlp.env` on each machine, loaded at import time via `python-dotenv` with `override=False`. No `.env` file in the repo, no `.env.example`.  
**Why:** The repo is public. The user does not want credentials stored in or near the repo even as examples.  
**Ref:** [`docs/SETUP.md`](docs/SETUP.md)

### Separate `parsed_pdfs` collection for PDF markdown (not embedded in `web_items`)
**Decided:** 2026-05-17  
**What:** A dedicated `ema_scraper.parsed_pdfs` collection stores the pymupdf4llm-parsed markdown for each PDF, keyed by URL (`_id = url`). Fields: `markdown`, `parsed_with`, `error`, `cache_path`, `ingested_at`. The corpus pipeline queries this collection directly rather than loading `.pkl` files from disk.  
**Why:** Three alternatives were considered and rejected:
- *Embed in web_items*: 600 MB extra storage in a collection that's conceptually about raw scrape metadata. Harder to rebuild if parsing is rerun.
- *Store only cache_path in web_items*: path is machine-specific; breaks across machines without Nextcloud.
- *Separate collection (chosen)*: URL as `_id` gives O(1) lookup; handles 65k PDFs including the ~4.6k not in `web_items`; `parsed_pdfs.find({error: ""})` directly iterates valid parsed content; collection can be dropped and rebuilt without touching `web_items`.  
**Implementation:** `scripts/ingest_parsed_pdfs.py` — walks the Scrapy cache with `os.walk` (not `Path.walk`, which is Python 3.12+), batch-upserts in groups of 500. 65,263 docs ingested; 10.5% parse-failure rate (`error != ""`); 2 docs skipped (corrupted pkl, markdown > 14 MB).  
**Corpus query:** `parsed_pdfs.find({"error": ""})` for strictly clean parses, or `{"markdown": {"$ne": ""}}` to also include 19,494 legacy-format docs.  
**Ref:** [`.claude/work/2026-05-17_07_pdf-mongodb-linking/exploration.md`](.claude/work/2026-05-17_07_pdf-mongodb-linking/exploration.md)

### MongoDB sync via Nextcloud (no cloud database account)
**Decided:** 2026-05-15  
**What:** `scripts/sync_mongo.sh export` dumps the local `ema_scraper` database to `~/Nextcloud/Datasets/mongo_sync/ema_scraper.archive`. The other machine imports it after Nextcloud syncs the file. A live SSH pull via Tailscale is also available when both machines are online simultaneously.  
**Why:** Free, symmetric, works asynchronously. No MongoDB Atlas or other managed database service required.  
**Ref:** [`docs/SETUP.md`](docs/SETUP.md) §5

### MongoDB runs in Docker (`mongo:8.0.4`) to survive kernel ≥ 6.19
**Decided:** 2026-05-29  
**What:** On marvin-gpu (Ubuntu 26.04 / Linux kernel 7.0), MongoDB is run as a Docker container pinned to **`mongo:8.0.4`**, bind-mounting the existing native data directory `/var/lib/mongodb` and running as the host `mongodb` uid:gid (`109:118`). Defined in `deploy/mongo/docker-compose.yml`; started together with Neo4j by `scripts/start_services.sh`. `MONGO_URI` is unchanged (`mongodb://localhost:27017/`).  
**Why:** Kernel ≥ 6.19 is flagged incompatible by MongoDB ([SERVER-121912](https://jira.mongodb.org/browse/SERVER-121912)). Empirically on this host: the **native 8.0.4 package starts then SIGSEGVs ~1 min in**; **newer 8.0.x images (`mongo:8.0` → 8.0.23) hard-refuse to start**; but the **`mongo:8.0.4` container runs fine** — a container shares the host kernel yet bundles its own older userspace/glibc, which dodges the SIGSEGV, and 8.0.4 predates the hard kernel gate added later in the 8.0.x line. This avoids rebooting into kernel `6.17.0-29-generic` (the only installed < 6.19 kernel that still has the NVIDIA driver built — `6.8.0-45` has none, so no CUDA for the embed run).  
**Constraints:** Pin stays at `8.0.4` — do not bump without re-testing on the live kernel. The native `mongod.service` and the container must never run against `/var/lib/mongodb` simultaneously (WiredTiger corruption); `start_services.sh` aborts if native `mongod` is active. Verified serving the real data: `parsed_documents` 80,083 / `parsed_pdfs` 65,263 / `web_items` 115,101 (the `link_graph` collection was never built — `LINKS_TO` edges are extracted at ingest).  
**Not chosen:** *Reboot into 6.17* — viable but the box is WiFi-only with no out-of-band console; the Docker route needs no reboot. *Upgrade MongoDB past 8.0.x* — later versions keep the hard kernel gate; no fix shipped as of 2026-05-29.  
**Ref:** [`deploy/mongo/README.md`](deploy/mongo/README.md), [`scripts/start_services.sh`](scripts/start_services.sh)

### Workflow registry collapsed: prompt_strategy as YAML field (Change 3 of harness refactoring)
> **Superseded 2026-06-25** — the workflow registry and the `prompt_strategy` axis were removed
> with the Workflow engine. A recipe's behaviour is set by its toolset + system-prompt file, not
> a prompt-strategy enum.

**Decided:** 2026-05-25  
**What:** The three `simple_rag_zero/few/cot` registry entries were removed and replaced with a single `simple_rag` entry. The prompt variant is now driven by `orchestration.prompt_strategy: zero_shot|few_shot|cot_self` in the YAML config rather than by the registry key. All workflow constructors renamed their `strategy` parameter to `prompt_strategy` to disambiguate it from `orchestration.strategy` (the registry key). No backward-compatibility aliases.  
**Why:** Adding a fourth prompt variant previously required three new registry entries, three builder functions, and equivalent expansion for every other strategy that supports prompts. The coupling between "orchestration shape" and "prompt variant" was artificial. Separating them means a new prompt file + one `_PROMPT_FILES` entry + a YAML change suffices.  
**Ref:** `HARNESS_REFACTORS.md` (deleted) Change 3

### Phoenix span attribute stamping via config_attributes() (Change 1 of harness refactoring)
**Decided:** 2026-05-25  
> **Superseded**: Phoenix was replaced by MLflow (2026-06-22) and `WorkflowRunner` deleted with the Workflow engine (2026-06-25). The *idea* survives: the resolved recipe is stamped as `ema.*` attributes on the MLflow turn span by `AgentWorkflowAdapter`, plus `ema.recipe` as a trace-level tag. (`HARNESS_REFACTORS.md` and `tests/test_span_attributes.py` referenced below are deleted.)

**What:** `WorkflowRunner.ainvoke` now stamps the active configuration onto the current OTel root span before delegating to the underlying workflow. Each workflow class exposes a `config_attributes() → dict[str, ...]` method. The `ema.*` namespace is used for all project-specific keys (e.g. `ema.orchestration.strategy`, `ema.retrieval.reranker`). `run_id` and `source` are passed through the inputs dict and stamped as `ema.run.id` / `ema.run.source`. Stamping is a silent no-op when Phoenix is disabled (non-recording span) or when a workflow lacks `config_attributes()` (warning once, then continues).  
**Why:** Without configuration on spans, Phoenix could not answer "show me all CRAG + reranker=sme runs below 0.6 faithfulness". For a project whose central purpose is comparing configurations, this was a blocker.  
**Ref:** `HARNESS_REFACTORS.md` (deleted) Change 1, `tests/test_span_attributes.py` (deleted)

### Shared retrieval factory build_retrieve_fn (Change 2 of harness refactoring)
**Decided:** 2026-05-25  
> **Superseded**: `build_retrieve_fn` / `harness/retrieve.py` / `AblationConfig` were deleted in the LlamaIndex retrieval refactor. The *idea* survives as the config-driven retrieval pipeline (`harness/retrieval/` transforms + rerankers, selected per recipe) shared by the app, demo, and eval paths. (`HARNESS_REFACTORS.md` referenced below is deleted.)

**What:** The inline `retrieve_fn` closure that was built inside `run_eval.py` (applying A1→base→A2→A3/A4 in order) was extracted into `build_retrieve_fn(ret_config, abl_config, index)` in `harness/retrieve.py`. A new `AblationConfig` dataclass carries query expansion, topic filter, and reranker settings parsed from the `ablation:` YAML section. All workflows accept an optional `retrieve_fn` parameter; when provided they call it instead of `retrieve_with_config()`. The factory attaches `.ablation_config` to the callable so `config_attributes()` can report the active ablation flags on the span.  
**Why:** The reranker (A3) could not compose with CRAG or ReAct because the ablation closure was only applied in `run_eval.py`'s retrieval eval loop, not in workflow execution. This is a real architectural limit. The factory also eliminates the drift between `app.py` and `run_eval.py` retrieval paths.  
**Ref:** `HARNESS_REFACTORS.md` (deleted) Change 2, `docs/RETRIEVAL.md` (was `docs/RETRIEVAL_PIPELINE.md`, removed)

### Three-layer separation: parsers → Mongo (parsed_documents) → PG (canonical)
> ⚠ **SUPERSEDED 2026-05-30.** The PG layer is removed; the flow is now parsers → Mongo `parsed_documents` → `harness.indexing` → Neo4j. Parser layer + `parsed_documents` survive; the PG sink does not. Retained for history.

**Decided:** 2026-05-26 (MIGR-001..017)  
**What:** The Mongo → Postgres ingest pipeline is split into three layers:

1. **Parsers (`corpus/parsers/`)** — each parser implements the `Parser` protocol (`name`, `version`, `parse(raw, url, content_type) → ParsedDocument`) and writes through `corpus.sources.parsed_documents.write_parsed_document`. Production parsers: `pymupdf4llm` (wraps the Scrapy-cache pickled holders) and `trafilatura` (wraps the `web_items.html_raw` extract call). Demo parser: `llamahub_pdf_PDFReader` behind the `[parsers-llamahub]` extra.
2. **Mongo `parsed_documents`** — compound unique key `(url, parser, parser_version)` so different parsers and different versions of the same parser coexist for one URL. This is the authoritative parsed-text store; the legacy `parsed_pdfs` and `web_items` collections become raw-input stores only.
3. **`harness/embed_pg.sync(parser_preference, …)`** — parser-agnostic. Reads `parsed_documents`, applies the preference selector per URL, computes `sha256(parsed.text)`, skips when it matches `documents.parsed_text_hash`, otherwise deletes the doc's chunks+links and re-chunks/embeds/upserts. Writes `parser`, `parser_version`, `parsed_at`, `parsed_text`, `parsed_text_hash` on every upsert.

The key design choices and what they replaced:

- **Compound key `(url, parser, parser_version)`** (resolves OQ-1). Lets parser-swap experiments be additive — write the new parser's rows, flip `parser_preference.yaml`, re-sync the affected URLs. Old rows are still there for rollback.  
- **`parsed_text` lives in PG too** (resolves OQ-3). Required so the sync can recompute `parsed_text_hash` from data in PG without re-reading Mongo, and so eval/debug tooling can see exactly which text was chunked. Adds storage cost but the determinism payoff is large.  
- **Phased transition via synthetic legacy reader** (resolves OQ-6). `corpus/sources/synthetic_legacy_reader.py` bridges `parsed_pdfs` + `web_items` to a `ParsedDocument` stream so the refactored sync runs against today's data **without** a one-shot backfill. The backfill (MIGR-012) then writes those rows into `parsed_documents` proper; MIGR-013 retires the bridge.  
- **Parser preference is YAML + CLI** (`harness/configs/parser_preference.yaml` + `--parser-preference content_type=parser`). Per-content_type the CLI override fully replaces the YAML list — there's no merge — which keeps the precedence model trivially explainable.

**Why:** The previous `embed_pg.py` had `from corpus.ingestion.pdf_normaliser import normalise_pdf_doc` and a function-scope `from corpus.ingestion.html_normaliser import normalise_html_doc`. Adding a parser meant touching the sync, the chunker's caller, and the eval pipeline. Worse: switching parsers for an experiment required re-embedding all 25 docs because the chunker was fed parser-specific markdown blends. The three-layer split removes both coupling problems and gives us a parser-swap workflow with measurable incremental cost (only URLs whose `parsed_text_hash` actually changed re-embed).

**Not chosen:**
- *Per-parser Mongo collections* (`parsed_documents_pymupdf4llm`, `parsed_documents_trafilatura`, …). Rejected — adds collection-discovery complexity, breaks the "find all parsers for a URL" query, and the index-explosion isn't worth saving a few bytes per row.
- *Nested-by-parser document shape* (`{url, parsers: {pymupdf4llm: {...}, trafilatura: {...}}}`). Rejected — partial-update semantics on subdocuments are messier than compound-key upserts, and the document size grows unboundedly as parser_versions accumulate.
- *Big-bang migration* (write a one-off script that rewrites everything in one PR). Rejected — would require a maintenance window, conflate the refactor with the backfill, and offer no incremental verification points. The synthetic reader lets each PR land independently.

**Ref:** `docs/RETRIEVAL.md` (was `docs/RETRIEVAL_PG.md`, removed) §13, [`.claude/work/2026-05-26_17_mongo-pg-data-architecture/`](.claude/work/2026-05-26_17_mongo-pg-data-architecture/)

### Link graph as retrieval cornerstone — extractor is parser-peer, sibling collection, enum-extended `link_type`
> ⚠ **NEVER BUILT / SUPERSEDED 2026-05-30.** This entry describes MIGR-018..025 as *shipped* with operational metrics (2.2M anchors, ~6 min, `file_link` defaults), but the code (`corpus/extractors/link_graph.py`, the Mongo `link_graph` collection, the `file_link`/`page_link` defaults) was **never actually committed or run** — verified in work unit `2026-05-30_19_retrieval-design-feedback` (and in the live data: no `link_graph` collection exists). Links are now extracted at ingest from `web_items.html_raw` into Neo4j `LINKS_TO` edges (see the Neo4j decision above). Retained as a cautionary record of doc/reality drift.

**Decided:** 2026-05-27 (MIGR-018..025)
**What:** Link extraction is now its own data-preparation layer (`corpus/extractors/link_graph.py`), peer to the parsers under `corpus/parsers/`. It walks raw HTML in `web_items.html_raw`, classifies every `<a href>` by URL extension into `file_link` / `page_link` / `external`, and writes results to a new Mongo `link_graph` collection keyed by URL (`_id`). The sync (`harness.embed_pg._prepare_from_parsed_doc`) joins `link_graph` for every HTML doc it processes and emits one PG `links` row per `ClassifiedAnchor` with the classified `link_type`. The `link_type` column in PG remains freeform `TEXT`; the recursive-CTE traversal in `harness.retrieve_pg._expand_via_links` and the `follow_links` ReAct tool default to `('hyperlink', 'reference_number', 'file_link')` (MIGR-020) so HTML→PDF expansion is the default retrieval behaviour.

**Why:** The audit `.claude/work/2026-05-27_18_scraper-link-extraction-audit/` established that the recursive-CTE auto-traversal is a **retrieval cornerstone** in this project's design — when semantic search underfetches, the system walks the link graph to discover structurally-relevant context (inspired by LlamaIndex's recursive retriever). User direction (2026-05-27): *"a cornerstone of the current approach is to utilize the links between pages to expand the context."* The MIGR-007 sync had dropped `_collect_html_links(html_raw)` as part of the parser-agnostic refactor, which silently shrank HTML→PDF traversal reach by 96 % on the live PG seed (867 PDF anchors → 31 across 98 docs, 65 of 98 docs lost every file_link). The repair has to ship before the production backfill (MIGR-013) so the full corpus lights up with the link graph intact in one pass.

The four key choices and what they replaced:

- **Extractor is a parser-peer layer (sibling Mongo collection)** — not folded into a parser's `meta['links']`. Reason: link extraction operates on `html_raw` (the upstream of any parser), so coupling it to a single `(url, parser, parser_version)` row would force re-extraction every time the parser swaps. A sibling collection keyed by URL is naturally parser-agnostic and survives parser-preference changes unchanged.
- **`link_type` as enum extension, not side column** — added `file_link` and `page_link` to the existing `links.link_type` column rather than introducing an `is_file boolean` side column. Reason: the recursive-CTE clause `l.link_type = ANY(%(link_types)s)` extends to a new value the moment it's in the default tuple — no schema migration, no parallel filter, no new index. The cost is one freeform string column that's already there.
- **`file_link` in the default traversal tuple, `page_link` out** — `file_link` recovers EMA's HTML→PDF cards that the old extraction lost, which is the audited retrieval-reach regression. `page_link` is dominated by site-wide nav links (per-page averages: ~8 file_links vs ~96 page_links on the 22k backfill), so promoting them to default would dilute traversal results with boilerplate. They stay in the enum for cases where eval shows nav expansion would help — promote per-config, not by default.
- **Phased delivery: B.1 first** — full-anchor extraction with extension classification (Option B.1 from the audit). Option B.2 (per-section provenance via the `.bcl-inpage-navigation` CSS layout) is deferred until a benchmark failure shows section-level filtering would help. User direction: extract from existing `html_raw`, no re-scrape.

**Operational evidence (2026-05-27):**
- Backfill over 22,743 `web_items` HTML rows: 2,279,311 anchors emitted (298,451 file_link / 1,834,301 page_link / 146,559 external), 0 errors, ~6 minutes wall time on marvin-gpu.
- Post-sync against the existing 98-doc HTML PG seed: `file_link=786`, `page_link=9,452`, `external=704` (versus 0 before; recovers ~94 % of the 836 PDF anchors the audit measured as lost).
- Recursive CTE smoke from an HTML seed with `link_types=['file_link']` returned ≥ 1 expanded PDF chunk — the cornerstone is wired end-to-end.

**Not chosen:**
- *Re-scraping with `EmaSpider.parse_with_sidebar`* — the rich per-section spider the user originally designed. Rejected per user direction; existing `html_raw` already has the anchors.
- *Bake link extraction into the trafilatura parser* (extend `corpus/parsers/trafilatura.py` to also return file_links on `ParsedDocument.meta`). Rejected — couples content extraction with link extraction, and a different HTML parser later would have to re-implement link extraction too. The sibling-collection layout keeps both concerns separable.
- *Selective scan inside the sync layer* — putting the BeautifulSoup walk in `harness/embed_pg.py`. Rejected — sync should stay thin; data preparation belongs in `corpus/`. Also makes per-URL re-extraction harder.
- *Promote `link_type` to a PG `ENUM` type* — would tighten typing but force a DDL migration every time a new value lands. Deferred to a follow-up if schema drift becomes an issue.

**Ref:** `docs/RETRIEVAL.md` (was `docs/RETRIEVAL_PG.md`, removed) §14, `.claude/work/2026-05-27_18_scraper-link-extraction-audit/` and `.claude/work/2026-05-26_17_mongo-pg-data-architecture/implementation-plan-link-graph.md` (work-unit artifacts, since pruned), MIGR-018..025.
