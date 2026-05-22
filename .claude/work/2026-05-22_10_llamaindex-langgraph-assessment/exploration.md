# Exploration: LangGraph + LlamaIndex Integration Assessment

## What the codebase actually does

### The bridge (EMARetriever, `harness/chains/retriever.py`)

LlamaIndex → LangChain conversion happens in one place: `EMARetriever(BaseRetriever)`.  
It calls `retrieve_with_config()` (LlamaIndex) and converts `(qa_id, score, meta)` tuples into `Document(page_content=node.text, metadata={...})`.  
After this conversion, all downstream LangGraph nodes see only `list[Document]` — they have no access to LlamaIndex's TextNode, docstore, or node relationships.

### What LlamaIndex actually provides today

| Component | Used? | How |
|-----------|-------|-----|
| `VectorStoreIndex` + FAISS | Yes | Dense retrieval on Q&A nodes |
| `BM25Retriever` | Yes | Keyword retrieval (hybrid with RRF) |
| Docstore (`get_node_by_id`) | Yes | O(1) node lookup for cross-ref traversal |
| BGE-large-en via `llama-index-embeddings-huggingface` | Yes | Embedding model (global Settings) |
| `DocumentSummaryIndex` | No | Deferred to Phase 4 |
| `NodeRelationship` | No | Cross-refs stored as raw metadata lists, not NodeRelationship objects |
| `ReActAgent` (LlamaIndex) | Deprecated | Replaced by LangGraph ReAct (`chains/agents/react.py`) |
| `PropertyGraphIndex` | No | Deferred to v2+ |
| LlamaIndex query engines | No | Replaced by direct LangChain LLM calls |
| LlamaIndex workflow orchestration | No | Replaced by LangGraph StateGraph |

**Net: LlamaIndex is used as a FAISS+BM25 wrapper with a docstore. The advanced features that justified choosing it (DocumentSummaryIndex, NodeRelationship, ReActAgent) are not in production.**

### What LangGraph provides today

- CRAG grading loop (grade → rewrite ↔ retrieve, up to `max_rewrite_cycles`)
- Review loop (generate → review → revise, up to `max_review_cycles`)
- ReAct tool-calling agent with 4 EMA-specific tools
- Stateful routing (PipelineState TypedDict)
- 9 registered pipeline strategies via single `get_chain()` entry point

This is a strong, legitimate use of LangGraph — its state machine semantics are the right fit for iterative retrieval-augmented workflows.

### Custom implementations that shadow LlamaIndex features

- `embed_hierarchical.py`: builds a parent-node index manually (summaries of source pages with child Q&A ids in metadata). This replicates what `DocumentSummaryIndex` would do natively, but outside LlamaIndex's query engine.
- `retrieve.py::_retrieve_recursive()`: cross-ref traversal via metadata lists. This replicates what `NodeRelationship` + recursive retrieval would do in LlamaIndex's native paradigm.
- `retrieve.py::_rrf_fuse()`: custom RRF implementation (not LlamaIndex's built-in fusion retriever).

---

## The honest tension

The original decision to pick LlamaIndex (2026-05-15) cited three justifications:
1. `DocumentSummaryIndex` for the PageIndex model
2. `NodeRelationship` for cross-ref modeling without a graph DB
3. `ReActAgent` for Ablation B

Currently:
- `ReActAgent` is deprecated, replaced by LangGraph's agent
- `NodeRelationship` is not used; cross-refs are stored as plain metadata
- `DocumentSummaryIndex` is deferred to Phase 4

The justification has eroded. What remains is LlamaIndex-as-infrastructure: FAISS wrapping, BM25, and a docstore that provides O(1) node lookup by ID. The hierarchical and cross-ref retrieval strategies are custom code layered on top.

---

## Structural constraints imposed by the dual-framework design

1. **Cross-ref traversal must happen inside the retriever, not inside the graph.** Once `EMARetriever.invoke()` returns `list[Document]`, LangGraph nodes can't traverse the docstore. If you want a LangGraph node that says "now follow cross-refs to find related Q&As," it has to call back through the EMARetriever wrapper (or directly into `harness/retrieve.py`). The current agent tools (`follow_cross_refs`) do this correctly, but it's a round-trip.

2. **Embedding model is global (LlamaIndex Settings).** LangChain doesn't control it. This is a one-way dependency: LlamaIndex's global state must be configured before any LangGraph node runs retrieval.

3. **Rich node metadata gets serialized to a flat dict.** If a future retrieval strategy needs to access node-level relationships or embedding vectors inside the LangGraph pipeline, it can't — they were dropped at the bridge.

4. **Multiple state schemas.** `PipelineState`, `AgentState`, `CRAGState` exist in parallel. `_extract_output()` normalizes them but it's extra surface area.

---

## What would a cleaner architecture look like?

### Option A: Lean into LlamaIndex natively (use its query engines + workflows)
Replace LangGraph with LlamaIndex Workflows (v0.10+) or just LlamaIndex's native agentic patterns. Use `DocumentSummaryIndex` properly. Use `RouterQueryEngine` for strategy dispatch. Pros: single framework. Cons: gives up LangSmith, LCEL composition, and the LangGraph state machine semantics that the current CRAG/review loops depend on.

### Option B: Keep the split, but be explicit about LlamaIndex's role
Acknowledge that LlamaIndex in this project is an infrastructure layer (FAISS + BM25 + docstore), not an agent/pipeline framework. The bridge (`EMARetriever`) is the correct seam. Future LlamaIndex features (DocumentSummaryIndex, if adopted) would remain behind the bridge. The LangGraph side never needs to know.

### Option C: Replace LlamaIndex with langchain-community equivalents
- Replace `VectorStoreIndex` with `langchain-community`'s FAISS wrapper
- Replace `BM25Retriever` with `langchain-community`'s BM25 retriever
- Replace the docstore with a plain dict keyed by qa_id
- Drop the bridge entirely; retrieval stays in LangChain
Pros: single framework, eliminates the bridge seam. Cons: loses BGE-large integration (would need explicit wiring), loses Phoenix/OpenInference tracing at the retrieval level, requires a rewrite of `embed.py`, `retrieve.py`, and `embed_hierarchical.py`.

---

## Verdict

**The current setup is coherent and not broken.** The bridge is clean. The state machine semantics in LangGraph are appropriate. No immediate refactor is warranted.

**The risk is drift:** if Phase 4 doesn't implement DocumentSummaryIndex or NodeRelationship, the two-framework overhead becomes pure cost with no return. The custom hierarchical index and cross-ref traversal are already duplicating LlamaIndex features outside LlamaIndex's native paradigm — if that continues, Option C becomes increasingly attractive.

**The critical question:** Do you plan to use `DocumentSummaryIndex` natively in Phase 4, or will you continue with the custom hierarchical index? If native: the current split makes sense and you'll finally justify LlamaIndex's inclusion. If custom: consider Option C as a Phase 2/3 cleanup item.
