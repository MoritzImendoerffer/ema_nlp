# Exploration — LlamaIndex-first retrieval refactor

Follows the design discussion in `../2026-05-30_19_retrieval-design-feedback/`.
Decision taken by the user: make LlamaIndex indexes first-class, config-driven,
no backwards compatibility.

## Current architecture (what exists on the checkpoint)

```
Mongo parsed_documents ──► embed_pg.sync ──► PG documents/chunks/links ──► retrieve_pg (raw SQL: dense/bm25/RRF + recursive CTE)
corpus.jsonl ───────────► embed.build_index (FAISS VectorStoreIndex) ───► retrieve.py (LlamaIndex retrievers, tuple output)
                                                                              │
workflows/* (simple_rag, crag, react, summarize, composites, review)  ◄──── retrieve_fn(query)->[(id,score,meta)]  OR  index
   │  get_workflow(name, index, llm, retrieve_fn, ...) → runner.ainvoke({question}) → {answer_text, docs, cited_qa_ids}
   ▼
app.py (Chainlit): profiles=strategies, settings, QueryCache (FAISS), fewshot_inject, 👍/👎→Phoenix
Phoenix/OpenInference: registered in app.py; WorkflowRunner._stamp_span stamps ema.* config attrs
```

Key seams found:
- `harness/workflows/registry.py:get_workflow(index, llm, retrieve_fn, ...)` — workflows
  accept **both** a LlamaIndex `index` and a tuple-returning `retrieve_fn`; when
  `retrieve_fn` is present they use it. This dual path is the thing to collapse.
- `app.py:_build_session_workflow` builds `retrieve_fn` via `build_retrieve_fn[_pg]`
  and passes it to `get_workflow`. `_load_index_sync` returns `None` for pgvector.
- `app.py:532` parses `"Q: … A: …"` out of `doc.text` for source cards — a
  corpus.jsonl assumption; breaks on narrative chunks.
- Result contract consumed by UI: `{answer_text, docs:[TextNode-like], cited_qa_ids}`.
- `corpus/ingestion/chunker.py:92` discards all non-leaf nodes (hierarchy lost).
- `harness/configs/retrieval_recursive.yaml` already sketches the target config
  vocabulary: `retrieval.strategy: flat|recursive|hierarchical|agentic` + `index:` block.
- pyproject has `llama-index-core>=0.12`, `-vector-stores-faiss`, `-retrievers-bm25`,
  `-embeddings-huggingface`, `-llms-anthropic/-openai`, `-readers-file`. **No graph-store
  package yet** — a `llama-index-graph-stores-*` dep is needed for OPEN-1.

## Target architecture (LlamaIndex-first)

```
Mongo parsed_documents (+ link data)
        │  ingestion: build LlamaIndex nodes
        ▼
   Node model:  Document entity nodes ──has_chunk──► Chunk nodes ──parent/child──► sub-chunks
                        └──────────────── links-to ───────────────► other Document nodes
        │
        ▼
   ┌── INDEX FACTORY  build_index(cfg.index) ───────────────────────────────┐
   │   kind=faiss_vector   → VectorStoreIndex(FaissVectorStore)             │
   │   kind=property_graph → PropertyGraphIndex(<PropertyGraphStore>)       │  ← OPEN-1
   │   (vector store also pluggable: simple | faiss | pgvector …)           │  ← OPEN-2
   └────────────────────────────────────────────────────────────────────────┘
        │ persisted (storage_context); rebuilt only when source/chunker changes
        ▼
   ┌── RETRIEVER FACTORY  build_retriever(cfg.retrieval, index) ─────────────┐
   │   v1: strategy=hierarchical → vector search on leaf chunks → merge up   │
   │       via parent/child → 1-hop links-to traversal (all in Neo4j)        │
   │   (registry seam; more strategies added only when a need appears)       │
   └────────────────────────────────────────────────────────────────────────┘
        │ returns a LlamaIndex BaseRetriever
        ▼
   workflows/* (re-seamed: take retriever/query-engine, not retrieve_fn)
        ▼
   app.py (unchanged UX) · Phoenix tracing (native retriever spans) · feedback stack
```

### Proposed config schema (extends retrieval_recursive.yaml)

```yaml
index:
  kind: property_graph            # only kind in v1 (INDEX_REGISTRY seam allows more)
  source: mongo_parsed_documents  # narrative corpus (not corpus.jsonl)
  scope: { committee: [], topic_prefix: "", limit: 2000 }   # subset-first (R3)
  store:
    graph: neo4j                  # Neo4jPropertyGraphStore — holds nodes/edges AND
                                  #   serves vector retrieval via Neo4j's native index
  chunking:
    parser: hierarchical          # multi-level; parent/child kept (R4/FR6)
    chunk_sizes: [2048, 512, 128] # big -> small, for small-to-big retrieval
  embed_model: BAAI/bge-large-en-v1.5
  edges: [links_to]               # extensible later

retrieval:
  strategy: hierarchical          # small-to-big merge + links-to traversal (v1)
  k: 10
  merge: true                     # merge retrieved leaves up to their parents
  graph:
    max_hops: 1
    edge_types: [links_to]
```

## How the two LlamaIndex halves map (from the _19_ doc-research)

- **Hierarchy / sub-nodes** → `HierarchicalNodeParser` + `AutoMergingRetriever`
  (and/or `RecursiveRetriever` over `IndexNode`s). Requires keeping parent nodes
  in the docstore — directly unblocked by fixing `chunker.py:92`.
- **`links-to` graph** → `PropertyGraphIndex` (the modern API; `KnowledgeGraphIndex`
  is deprecated as of LlamaIndex 0.10.53, confirmed via context7). Needs a
  `PropertyGraphStore` (OPEN-1). "Start with links-only, extend to typed edges
  later" maps cleanly onto PG's schema-free → schema-guided path.

## Integration boundaries (must stay working)

- **Chat UI:** swap `_load_index_sync`/`_build_session_workflow` to call the new
  factories; generalize source-card rendering + `cited_qa_ids` to doc/chunk ids.
- **Tracing:** Phoenix `register(auto_instrument=True)` already instruments
  LlamaIndex; native retriever/query-engine spans are a bonus. Preserve
  `WorkflowRunner._stamp_span` + `config_attributes()` (extend keys for index/retriever).
- **Feedback:** `QueryCache` (FAISS over query embeddings), `fewshot_inject`,
  `rating` (root-span lookup by recency) — all independent of the retrieval backend;
  keep `run_id` plumbing through `ainvoke`.

## Task plan — see implementation-plan.md + state.json (14 tasks, LIR-001..014)

The original 10-step sketch was replaced after the hierarchical-default + benchmark-
removal decisions. The authoritative breakdown lives in implementation-plan.md /
state.json. Highlights: **LIR-001** removes the benchmark suite (archived); the index is
a **hierarchical PropertyGraphIndex on Neo4j only** (no FAISS); **LIR-008** carries a
timeboxed spike on how small-to-big merge composes with PropertyGraphIndex/Neo4j; the old
retrieval/PG stack is deleted (LIR-012) only after the new path is wired (LIR-010).

## Decisions — RESOLVED (see requirements.md R1–R5)
Neo4j PropertyGraphIndex (all items) · Postgres dropped · subset-first · **hierarchical
default, no FAISS** · benchmark suite removed completely (preserved on
`archive/pre-llamaindex-refactor`).
