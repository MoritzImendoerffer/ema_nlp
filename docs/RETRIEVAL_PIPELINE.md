# Retrieval pipeline

How a query becomes a ranked list of Q&A passages — from raw text to reranked results.

---

## LlamaIndex packages in use

| Package | Role |
|---------|------|
| `llama-index-core` | `VectorStoreIndex`, `StorageContext`, `TextNode`, `load_index_from_storage` |
| `llama-index-embeddings-huggingface` | `HuggingFaceEmbedding` — wraps sentence-transformers |
| `llama-index-vector-stores-faiss` | `FaissVectorStore` — wraps faiss-cpu |
| `llama-index-retrievers-bm25` | `BM25Retriever` — wraps rank-bm25 |
| `llama-index-llms-anthropic` | `Anthropic` LLM wrapper — used by `harness/llms.py` for all synthesis, reranking, and agent steps |
| `openinference-instrumentation-llama-index` | Auto-traces all LlamaIndex calls to Arize Phoenix via OTLP |

LlamaIndex's `Settings.llm` is set to `None` in the **retrieval path** (`harness/embed.py`, `harness/retrieve.py`) — all retrieval steps are embedding-only. Synthesis, reranking, and agent planning all go through LlamaIndex Workflows (`harness/workflows/`) using the `Anthropic` LLM from `harness/llms.py`.

---

## Index construction (`harness/embed.py`)

### 1. QARecord → TextNode

Each corpus record becomes one `TextNode`:

```
id_      = qa_id           (stable 16-hex hash, used as primary key)
text     = "Q: {question}\n\nA: {answer}"
metadata = {all QARecord fields: qa_id, source_url, source_type,
            source_title, topic_path, cross_refs, extraction_confidence,
            reference_number, revision, last_updated}
excluded_embed_metadata_keys = [all metadata keys]
```

The `excluded_embed_metadata_keys` list ensures that **only the Q+A text** is
passed to the embedding model — metadata labels are not baked into the vector.

### 2. FAISS flat-L2 index

```python
faiss_index = faiss.IndexFlatL2(1024)   # 1024 = BGE-large-en output dim
vector_store = FaissVectorStore(faiss_index=faiss_index)
storage_context = StorageContext.from_defaults(vector_store=vector_store)
index = VectorStoreIndex(nodes, storage_context=storage_context, show_progress=True)
```

`IndexFlatL2` performs an **exact, exhaustive** L2-distance search over all 26k
vectors. No HNSW, no IVF partitioning. This is correct at 26k records (milliseconds
per query) and avoids the recall loss of approximate methods.

### 3. Persistence

```
harness/index/
├── faiss.index               ← FAISS flat-L2 vectors (~100 MB for 26k × 1024-dim float32)
├── docstore.json             ← full TextNode text + metadata for every record
├── default__vector_store.json ← maps vector ids to node ids
├── index_store.json          ← top-level index registry
├── graph_store.json          ← placeholder (empty, written by LlamaIndex)
└── image__vector_store.json  ← placeholder (empty, written by LlamaIndex)
```

**Reload check**: `build_index()` checks for `harness/index/docstore.json`. If it
exists and `force=False`, it reloads without re-embedding:

```python
faiss_index = faiss.read_index("harness/index/faiss.index")
vector_store = FaissVectorStore(faiss_index=faiss_index)
storage_context = StorageContext.from_defaults(
    vector_store=vector_store, persist_dir="harness/index"
)
index = load_index_from_storage(storage_context)
```

Reload is fast (~2 s). Rebuild from scratch takes ~25 min for 26k records with BGE-large-en.

---

## Embedding model (`harness/providers.py`)

`Settings.embed_model` is set once at startup via `configure_embed_model()`:

```python
Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-large-en-v1.5")
Settings.llm = None
```

`Settings` is LlamaIndex's global config object. Both the index builder and the
dense retriever read `Settings.embed_model` implicitly — they don't receive the
model as an argument unless explicitly passed (test override path).

The embedding model is used in two places:
1. **Index build** — embed each node's `text` field once
2. **Query time** — embed the incoming query string with the same model

Switching models requires a full index rebuild since the vector space changes.

---

## Retrieval modes (`harness/retrieve.py`)

All modes return `list[RetrievalResult]` where `RetrievalResult = (qa_id: str, score: float, metadata: dict)`.

### Dense (A0)

```python
retriever = index.as_retriever(similarity_top_k=k)
nodes = retriever.retrieve(query)
```

Internally:
1. LlamaIndex calls `Settings.embed_model.get_text_embedding(query)`
2. FAISS `IndexFlatL2.search(query_vector, k)` — exact L2 scan over all 26k vectors
3. Returns `NodeWithScore[]` ordered by L2 distance (lower = better)
4. Scores are negated L2 distances (higher = better) after LlamaIndex normalisation

**Strength**: Semantic similarity — finds conceptually related passages even with
different wording.  
**Weakness**: Misses exact-match tokens, abbreviations, and precise numbers
(e.g. "26.5 ng/day" — benchmark-confirmed failure that motivated hybrid mode).

### BM25

```python
retriever = BM25Retriever.from_defaults(docstore=index.docstore, similarity_top_k=k)
nodes = retriever.retrieve(query)
```

Internally:
1. `BM25Retriever.from_defaults` builds a BM25 index from the docstore at call time
   (no persistence — rebuilt on every retrieval call, ~0.5 s for 26k docs)
2. Tokenises all node texts and the query
3. Ranks by BM25 TF-IDF scores

**Strength**: Exact term matching, precise regulatory codes, abbreviations, numbers.  
**Weakness**: No semantic generalisation — misses synonyms and paraphrase.

> **Note**: The BM25 index is rebuilt from the docstore on every retrieval call.
> For production use at higher query volume this should be cached as a session-level
> object. Currently it's not a bottleneck at interactive speeds.

### Hybrid — Reciprocal Rank Fusion (A0+)

Both retrievers are run independently for top-k results each, then merged:

```
RRF score(d) = Σ_r  1 / (K + rank_r(d))     K = 60 (Cormack et al. 2009)
```

```python
dense_results = make_dense_retriever(index, k).retrieve(query)
bm25_results  = make_bm25_retriever(index, k).retrieve(query)
fused = _rrf_fuse([dense_results, bm25_results], k)
```

Documents appearing in both lists get a double contribution. A document ranked 1st
in one list and absent from the other scores `1/61 ≈ 0.016`. A document ranked 1st
in both lists scores `2/61 ≈ 0.033`. RRF is robust to score-scale differences between
the two retrievers — only rank position matters.

This is the **default mode** for both the chat UI and the `baseline_a0plus` eval run.

---

## Ablation A pipeline (`harness/ablations/`)

The ablation pipeline wraps the base retrieval in up to four post/pre-processing steps.
All steps are opt-in via YAML config.

```
query
  │
  ▼ A1 — Query expansion (optional)
  │   QueryExpander: bidirectional acronym↔canonical expansion
  │   e.g. "MAH" → "Marketing Authorisation Holder"
  │   Context-gated: ambiguous acronyms (AI, MA) only expand when context is clear
  │
  ▼ Core retrieval (dense | bm25 | hybrid)
  │
  ▼ A2 — Topic filter (optional)
  │   "keyword" mode: post-filter by topic_path substring
  │   "concept" mode: pre-filter by IDMP concept metadata tag
  │   Falls back to full results if fewer than min_results pass
  │
  ▼ A3 or A4 — LLM reranker (optional, one call per chunk)
  │   A3: SME rubric (harness/prompts/relevance_rubric_sme.md) — 0/1/2 score
  │   A4: generic "is this relevant?" prompt — 0/1/2 score
  │   Calls Claude Haiku per chunk; max_chunks caps API spend (default: 5)
  │
  ▼ ranked RetrievalResult list
```

### A2 concept mode detail

`make_concept_retriever(index, query, k)` calls `index.as_retriever(similarity_top_k=k)`
with a metadata filter on the `"concept"` field. This requires `scripts/tag_concepts.py`
to have been run first to populate concept metadata on each node. Without that step,
the filter matches nothing and the function falls back to a standard dense retriever.

### A3/A4 reranker detail

Each reranker:
1. Takes the top `max_chunks` results from upstream
2. Calls the LLM (`get_llm('reranker')` — configured in `models.yaml`) with the query + node text + scoring rubric
3. Extracts the `0/1/2` score from the response text
4. Re-sorts results by LLM score descending
5. Returns the reranked list (original score preserved in metadata)

Two interfaces are available:
- **`rerank(results, query, index)`** — tuple-based (`RetrievalResult` list); used by `run_eval.py`
- **`SMERerankerPostprocessor` / `GenericRerankerPostprocessor`** — `BaseNodePostprocessor` subclasses that accept `list[NodeWithScore]` and produce a distinct Phoenix span per call

The postprocessor interface (`_postprocess_nodes`) is the preferred path for new code as it integrates cleanly with LlamaIndex's tracing pipeline.

---

## Cross-reference traversal (`harness/embed.py`)

```python
def follow_cross_refs(index: VectorStoreIndex, qa_id: str) -> list[TextNode]:
    node = index.docstore.get_node(qa_id)
    return [index.docstore.get_node(ref) for ref in node.metadata["cross_refs"]]
```

`cross_refs` is a list of `qa_id` strings (e.g. "see Q&A 3" links extracted during
corpus building). Following them is O(1) per hop via docstore key lookup — no
re-embedding or retrieval. This enables multi-hop T3 queries in future ablation B
(process-reward agent), where the agent can expand its context by following explicit
document links.

Currently `follow_cross_refs` is implemented but not wired into the retrieval path —
it is available for the planned ReActAgent ablation.

---

## Retrieval strategies (`harness/retrieve.py` → `RetrievalConfig`)

Retrieval strategies are orthogonal to modes (dense/bm25/hybrid) and are configured
via `RetrievalConfig`:

```python
from harness.retrieve import RetrievalConfig

cfg = RetrievalConfig(
    strategy="recursive",  # flat | recursive | hierarchical | agentic
    mode="hybrid",
    k=10,
    recursive=RecursiveConfig(max_hops=1),
)
results = retrieve_with_config(cfg, index, query)
```

### `flat` (default)

Standard top-k retrieval using the selected mode. No post-processing.
Used by all baseline and ablation A eval runs.

### `recursive` — cross_ref expansion

Flat retrieval followed by automatic expansion of `cross_refs` edges up to `max_hops`
hops. Initial top-k results are returned at the front; expanded cross-reference nodes
are appended after, deduplicated by `qa_id`.

```python
cfg = RetrievalConfig(strategy="recursive", mode="hybrid", k=10,
                      recursive=RecursiveConfig(max_hops=1))
```

Use for T3 multi-hop questions where the answer requires traversing document cross-references.

### `hierarchical` — page → Q&A drill-down

Two-level retrieval requiring a separate hierarchical index
(`harness/index/hierarchical/`) built by `harness.embed_hierarchical`:

1. Retrieve top-`top_doc_k` parent (page-level) nodes from the hierarchical index
2. Collect all child `qa_id` entries in those pages' `child_qa_ids` metadata
3. Fetch child nodes from the flat docstore and re-score by dense similarity

Build the parent index:
```bash
python -m harness.embed_hierarchical
```

Configure:
```yaml
retrieval:
  strategy: hierarchical
  k: 10
  hierarchical:
    top_doc_k: 5
    summary_index_dir: harness/index/hierarchical
```

Falls back to flat dense retrieval if `hier_index` is not provided or `child_qa_ids` is empty.

### `agentic` — delegated to LlamaIndex `FunctionAgent`

Not handled by `retrieve_with_config`. Pass to `harness.workflows.registry.get_workflow("react")` instead.

---

## Chat UI flow (`app.py`)

```python
# At session start — runs in a thread pool to avoid blocking the async event loop
index = await asyncio.to_thread(_load_index_sync)
pipeline = await asyncio.to_thread(_build_session_workflow, index)  # WorkflowRunner

# Per message — single WorkflowRunner.ainvoke() call
result = await pipeline.ainvoke({"question": query, "few_shot_context": few_shot_block})
# → result["answer_text"], result["docs"], result["cited_qa_ids"]
```

LlamaIndex spans are automatically captured by `LlamaIndexInstrumentor` into Phoenix
traces. 👍/👎 button clicks annotate the root span stored in `cl.user_session`.

---

## What LlamaIndex does and does NOT do here

LlamaIndex handles both **retrieval and orchestration**. All strategies are implemented
as typed, event-driven `Workflow` steps in `harness/workflows/`.

| Capability | Status | Implementation |
|------------|--------|----------------|
| Vector similarity search | **Used** | `VectorStoreIndex.as_retriever()` → FAISS |
| BM25 keyword retrieval | **Used** | `BM25Retriever.from_defaults(docstore=...)` |
| Docstore key lookup | **Used** | `index.docstore.get_node(qa_id)` — O(1) by qa_id |
| Cross-ref traversal | **Used** | `follow_cross_refs()` via `metadata["cross_refs"]` |
| Index persistence / reload | **Used** | `StorageContext.persist_dir` + `load_index_from_storage()` |
| Auto-instrumentation | **Used** | `LlamaIndexInstrumentor` → Arize Phoenix OTLP |
| Workflow orchestration | **Used** | `Workflow` + typed `Event` subclasses (`harness/workflows/`) |
| ReAct agent | **Used** | `ReActNativeWorkflow` — hand-written think/act/observe loop in `react_native.py`; per-step Phoenix spans |
| LLM calls | **Used** | LlamaIndex `Anthropic` LLM via `harness/llms.py` |
| LLM synthesis via `as_query_engine()` | Not used | Claude called directly via LlamaIndex `Anthropic` LLM |
| `DocumentSummaryIndex` | Not used | Page-level parent nodes built manually in `embed_hierarchical.py` |
| `QueryFusionRetriever` | Not used | Requires OpenAI install; RRF implemented directly in `_rrf_fuse()` |
| Node post-processors / rerankers | **Used** | `SMERerankerPostprocessor` (A3) + `GenericRerankerPostprocessor` (A4) implement `BaseNodePostprocessor`; tuple-based `rerank()` also available |
| `NodeRelationship.RELATED` | Not used | Cross-refs stored as plain `metadata["cross_refs"]` list (metadata edges, not graph DB); `follow_cross_refs()` does docstore lookup |
| Streaming retriever | Not used | Retrieval is synchronous; synthesis streams inside the Workflow step |
