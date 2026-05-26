# Architecture and scope decisions

Running log of decisions that are not obvious from the code. Each entry has a rationale and a link to the fuller exploration if one exists. Read this after a break to reconstruct why things are the way they are.

See `OPEN_QUESTIONS.md` for decisions not yet made.

---

## Scope

### EMA human-regulatory Q&As only — v1 scope lock
**Decided:** project start  
**What:** Corpus and benchmark cover only EMA human-regulatory Q&A documents (HTML accordions and numbered-section PDFs). No EPARs, no FDA content, no biomedical literature, no clinical trial documents, no multilingual content.  
**Why:** Keeps the corpus extractable in one week of evenings, the benchmark curated by one SME, and the ablations controlled. Complexity is introduced only when a benchmark failure demands it.  
**Deferred to v2+:** EPARs, multilingual (OPUS EMEA is a hook), biomedical/clinical questions beyond regulatory scope.

### No ontology or graph infrastructure in v1
**Decided:** project start; refined 2026-05-15  
**What:** IDMP/SPOR ontology and Neo4j are out of scope for v1. The IDMP RDF files are used only for lightweight concept tagging on LlamaIndex nodes (TASK-016.5) — simple string matching against concept labels, stored as node metadata for metadata filtering. No graph DB, no entity-linking, no SPARQL.  
**Why:** The `cross_refs` field in the corpus schema already encodes the most useful graph structure (Q&A cross-references). LlamaIndex `NodeRelationship` captures these without Neo4j. Full graph-RAG is only justified if Ablation B shows the cross-ref traversal tool is insufficient on T3 questions.  
**Deferred to v2+:** PropertyGraphIndex, Neo4j, SPARQL queries over IDMP.  
**Ref:** [`project_roadmap/ROADMAP.md`](project_roadmap/ROADMAP.md) — "What's explicitly deferred to v2+"

---

## Retrieval framework

### LlamaIndex as the RAG framework
**Decided:** 2026-05-15  
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
**Ref:** [`docs/RETRIEVAL_PG.md`](docs/RETRIEVAL_PG.md), [`.claude/work/2026-05-25_16_pgvector-narrative-corpus/`](.claude/work/2026-05-25_16_pgvector-narrative-corpus/) (28-task work unit), [`corpus/pg_schema.sql`](corpus/pg_schema.sql), [`harness/retrieve_pg.py`](harness/retrieve_pg.py)

### BGE-large-en as the embedding model (v1)
**Decided:** project start  
**What:** `BAAI/bge-large-en` via `llama-index-embeddings-huggingface` for both document and query embeddings. Same model used for the query cache similarity search so the embedding spaces are aligned.  
**Why:** Strong English retrieval performance, freely available, runs on CPU. Avoids an API embedding dependency.  
**Note:** Not yet benchmarked against alternatives — document the choice and revisit if retrieval metrics in Phase 3 are disappointing.

### LlamaIndex Workflows for all orchestration (supersedes LangChain + LangGraph)
**Decided:** 2026-05-22  
**What:** LlamaIndex Workflows (`harness/workflows/`) handle all prompt chains, agent loops, and pipeline orchestration. LangChain, LangGraph, and LangSmith are removed from the stack entirely.  
**Why:** The LangChain bridge (`EMARetriever`) stripped node metadata, required global LlamaIndex state to be configured before any LangGraph node ran retrieval, and forced two divergent ReAct implementations. Using LlamaIndex Workflows end-to-end eliminates the bridge, keeps node metadata intact throughout the pipeline, and reduces dependency count.  
**Architecture:** `harness/workflows/registry.py` provides a single `get_workflow(name, index, llm)` entry point for 9 registered strategies. Every strategy is a typed, event-driven `Workflow` (or `FunctionAgent`/`AgentWorkflow` for ReAct). All strategies expose `.invoke()` and `.ainvoke()` via `WorkflowRunner`.  
**Not chosen:** Using LangGraph for orchestration — the impedance mismatch at the LlamaIndex/LangChain boundary outweighed the benefits of LangGraph's state machine semantics for this retrieval-centric project.  
**Ref:** [`.claude/work/2026-05-22_10_llamaindex-langgraph-assessment/`](.claude/work/2026-05-22_10_llamaindex-langgraph-assessment/)

### Role/model separation in models.yaml
**Decided:** 2026-05-23  
**What:** `harness/configs/models.yaml` is restructured into two top-level sections:
- `models:` — model definitions keyed by a stable name (e.g. `claude_haiku`, `claude_opus`, `olmo_32b`, `local_qwen32`). Each entry has `provider`, `model_id`, `max_tokens`, `temperature`, and optionally `api_base` + `api_key_env` for `openai_compatible` servers.
- `roles:` — maps functional roles (`agent`, `grader`, `rewriter`, `reranker`, `judge`, `reviewer`) to model names. Change a role here to swap the model everywhere it's used.

`get_llm(role_name)` (in `harness/llms.py`) replaces `get_llm(tier_id)`. `load_model_for_role(role_name)` replaces `load_tier(tier_id)`. The constants `TIER_MID`, `TIER_FRONTIER`, `TIER_OLMO`, `TierId` are removed from hot paths.  
**Why:** The old `tier_id` conflated two concerns: which model to use AND what it's used for. Swapping the grader to a local model for offline runs required touching every call site. Roles decouple these: `roles.grader: local_qwen32` swaps only the grader with no code change.  
**Default role mapping:** grader/rewriter/reranker → `claude_haiku`; agent/judge/reviewer → `claude_opus`. Note: `agent` was initially Haiku but promoted to Opus after HITL-004a diagnosis showed Haiku skips tool calls in the ReAct loop (see `.claude/work/2026-05-24_12_hitl-pipeline-gaps/react_diagnosis.md`).

### Native ReAct workflow (`react_native.py`) as the default `react` strategy
**Decided:** 2026-05-23  
**What:** The registry key `react` now points to `ReActNativeWorkflow` (`harness/workflows/react_native.py`), a hand-written LlamaIndex `Workflow` where every agent action is a separate `@step`. The legacy `FunctionAgent`/`AgentWorkflow` implementation (`react.py`) was deleted (HITL-001, 2026-05-24).  
**Why:** `FunctionAgent`/`AgentWorkflow` wraps the entire ReAct loop in a single span — Phoenix can label the final answer but not individual tool calls or thoughts. `ReActNativeWorkflow` splits each think/act/observe into its own `@step`, so Phoenix traces show per-step spans that the HITL annotation system can label independently (`step_quality: good/suboptimal/wrong`).  
**Architecture:** Events: `ThoughtEvent`, `ActionEvent`, `ObservationEvent`, `FinishEvent` (all in `events.py`). Steps: `think` (StartEvent|ObservationEvent → ThoughtEvent|FinishEvent), `act` (ThoughtEvent → ActionEvent), `observe` (ActionEvent → ObservationEvent), `finish` (FinishEvent → StopEvent). Max iterations guard defaults to 5. Same 4 tools as `react_legacy`: `ema_search`, `follow_cross_refs`, `filter_by_topic`, `get_qa_by_id`.  
**Not chosen:** Keeping `FunctionAgent` for tracing — it does not expose per-step events to Phoenix.

### `orchestration:` block as the answer-generation schema in eval configs
**Decided:** 2026-05-23  
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

### Arize Phoenix + OpenInference for model-agnostic tracing
**Decided:** 2026-05-15  
**What:** Arize Phoenix (self-hosted, open source) captures every retrieval step, reranking call, and LLM call as an inspectable span tree. Instrumented via `LlamaIndexInstrumentor` at the framework level — works regardless of which LLM is used (Claude, GPT, OLMo 3, local models). Per-run trace export (`traces.jsonl`) is saved alongside config and results in `results/<run_id>/`.  
**Why:** OlmoTrace (the other tracing tool mentioned in the roadmap) is OLMo-specific. Phoenix covers all models. Self-hosted means no cloud account, traces stay local.  
**Ref:** [`project_roadmap/LEAKAGE.md`](project_roadmap/LEAKAGE.md) §7.5 for OlmoTrace context; [`.claude/work/2026-05-15_04_agentic-memory-architecture/exploration.md`](.claude/work/2026-05-15_04_agentic-memory-architecture/exploration.md)

---

## Feedback and online learning

### Phoenix annotations as the feedback store (not SQLite)
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
**Why:** Standard few-shot prompting. Every injected example is traceable (its `run_id` links to a Phoenix trace), satisfying the reproducibility requirement.  
**Implementation:** `harness/fewshot_inject.py:get_fewshot_context(query_vec, cache, k=3, min_rating=4)` — injected via `app.py` (always, when ≥ 3 rated entries exist) and `run_eval.py` (opt-in via `cache_inject: true` in YAML). Suppresses injection when fewer than `min_examples` (default 3) rated entries exist — fails closed.

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

### Workflow registry collapsed: prompt_strategy as YAML field (Change 3 of harness refactoring)
**Decided:** 2026-05-25  
**What:** The three `simple_rag_zero/few/cot` registry entries were removed and replaced with a single `simple_rag` entry. The prompt variant is now driven by `orchestration.prompt_strategy: zero_shot|few_shot|cot_self` in the YAML config rather than by the registry key. All workflow constructors renamed their `strategy` parameter to `prompt_strategy` to disambiguate it from `orchestration.strategy` (the registry key). No backward-compatibility aliases.  
**Why:** Adding a fourth prompt variant previously required three new registry entries, three builder functions, and equivalent expansion for every other strategy that supports prompts. The coupling between "orchestration shape" and "prompt variant" was artificial. Separating them means a new prompt file + one `_PROMPT_FILES` entry + a YAML change suffices.  
**Ref:** [`HARNESS_REFACTORS.md`](HARNESS_REFACTORS.md) Change 3

### Phoenix span attribute stamping via config_attributes() (Change 1 of harness refactoring)
**Decided:** 2026-05-25  
**What:** `WorkflowRunner.ainvoke` now stamps the active configuration onto the current OTel root span before delegating to the underlying workflow. Each workflow class exposes a `config_attributes() → dict[str, ...]` method. The `ema.*` namespace is used for all project-specific keys (e.g. `ema.orchestration.strategy`, `ema.retrieval.reranker`). `run_id` and `source` are passed through the inputs dict and stamped as `ema.run.id` / `ema.run.source`. Stamping is a silent no-op when Phoenix is disabled (non-recording span) or when a workflow lacks `config_attributes()` (warning once, then continues).  
**Why:** Without configuration on spans, Phoenix could not answer "show me all CRAG + reranker=sme runs below 0.6 faithfulness". For a project whose central purpose is comparing configurations, this was a blocker.  
**Ref:** [`HARNESS_REFACTORS.md`](HARNESS_REFACTORS.md) Change 1, [`tests/test_span_attributes.py`](tests/test_span_attributes.py)

### Shared retrieval factory build_retrieve_fn (Change 2 of harness refactoring)
**Decided:** 2026-05-25  
**What:** The inline `retrieve_fn` closure that was built inside `run_eval.py` (applying A1→base→A2→A3/A4 in order) was extracted into `build_retrieve_fn(ret_config, abl_config, index)` in `harness/retrieve.py`. A new `AblationConfig` dataclass carries query expansion, topic filter, and reranker settings parsed from the `ablation:` YAML section. All workflows accept an optional `retrieve_fn` parameter; when provided they call it instead of `retrieve_with_config()`. The factory attaches `.ablation_config` to the callable so `config_attributes()` can report the active ablation flags on the span.  
**Why:** The reranker (A3) could not compose with CRAG or ReAct because the ablation closure was only applied in `run_eval.py`'s retrieval eval loop, not in workflow execution. This is a real architectural limit. The factory also eliminates the drift between `app.py` and `run_eval.py` retrieval paths.  
**Ref:** [`HARNESS_REFACTORS.md`](HARNESS_REFACTORS.md) Change 2, [`docs/RETRIEVAL_PIPELINE.md`](docs/RETRIEVAL_PIPELINE.md)

### Three-layer separation: parsers → Mongo (parsed_documents) → PG (canonical)
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

**Ref:** [`docs/RETRIEVAL_PG.md`](docs/RETRIEVAL_PG.md) §13, [`.claude/work/2026-05-26_17_mongo-pg-data-architecture/`](.claude/work/2026-05-26_17_mongo-pg-data-architecture/)
