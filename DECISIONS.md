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
**Not chosen as the retrieval engine:** LangChain/LangGraph — better for prompt-chain-centric work; LlamaIndex is the superior choice for structured document retrieval and docstore indexing.  
**Note:** LangChain + LangGraph were subsequently adopted for the chain orchestration layer on top of LlamaIndex (see decision below). The retrieval engine decision stands unchanged.  
**Ref:** [`.claude/work/2026-05-15_04_agentic-memory-architecture/exploration.md`](.claude/work/2026-05-15_04_agentic-memory-architecture/exploration.md)

### FAISS as the vector store backend (v1)
**Decided:** project start (confirmed 2026-05-15)  
**What:** FAISS flat index for both the document index and the query cache index. In-memory-friendly, no server required, persisted to `harness/index/`.  
**Why:** Sufficient for the corpus size (~200–2000 Q&A records). If the corpus grows beyond ~100k records or latency becomes an issue, Qdrant is the natural upgrade path (LlamaIndex has a Qdrant vector store adapter).  
**Deferred:** Qdrant, Chroma, Weaviate — only if FAISS becomes a bottleneck.

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
**Default role mapping:** agent/grader/rewriter/reranker → `claude_haiku`; judge/reviewer → `claude_opus`.

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
**Decided:** 2026-05-15  
**What:** At query time, the top-k highest-rated past trajectories (rating ≥ 4/5) for similar questions are fetched from the query cache and injected into the agent's planning prompt as few-shot examples. No weights updated. All learning is in-context.  
**Why:** Standard few-shot prompting. Every injected example is traceable (its `run_id` links to a Phoenix trace), satisfying the reproducibility requirement.

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
