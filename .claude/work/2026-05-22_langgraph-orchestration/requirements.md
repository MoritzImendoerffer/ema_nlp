# Requirements — LangGraph Orchestration

## Goal
Integrate LangGraph as the **orchestration layer** for composing retrieval, summarization,
and review (QA) agents. LlamaIndex stays as the retrieval and memory backend.

## User intent
- Keep `EMARetriever` (LlamaIndex FAISS+BM25) unchanged — it already works
- Use LangGraph graphs to wire together multi-step agentic pipelines
- Be able to quickly swap or add nodes (e.g. a summarization step before generation,
  or a self-review loop after generation) without rewriting the whole pipeline
- The `CHAIN_REGISTRY` pattern should still be the single dispatch point

## Functional requirements

### F1 — Composable node library
Nodes for retrieval, summarization, generation, and review should be reusable across
different pipeline configurations without copy-pasting.

### F2 — Summarization agent
A dedicated LangGraph node (or subgraph) that condenses a list of retrieved `Document`
objects into a focused, citation-preserving summary for downstream generation.

### F3 — Review (QA) agent
A post-generation review node that calls the judge LLM (faithfulness + correctness)
and can optionally trigger a regeneration loop (capped at N cycles).

### F4 — Pipeline configurability
A `build_pipeline()` factory that accepts a config (dict or dataclass) specifying
which phases to include. New strategies = new configs, not new code.

### F5 — Registry integration
Named pipeline strategies registered in `CHAIN_REGISTRY` so `run_eval.py`,
LangSmith evals, and `app.py` all use the same dispatch mechanism.

### F6 — LlamaIndex memory compatibility
LlamaIndex `VectorMemory` / `ChatMemoryBuffer` usable as an optional tool,
not forced into the pipeline state (keeps eval repeatable).

## Non-functional requirements

### N1 — Eval repeatability
All pipeline runs must be deterministic (cache disabled, no stateful memory side-effects).
`MemorySaver` checkpointing is only active in interactive sessions.

### N2 — Tracing
All LangGraph nodes appear as distinct spans in Phoenix / LangSmith traces.
No new tracing configuration required.

### N3 — Backwards compatibility
Existing `simple_rag_*`, `react`, and `crag` strategies continue to work unchanged.

## Out of scope
- Multi-turn conversational memory in the benchmark eval loop
- Parallel agent invocations within a single pipeline run
- LlamaIndex `DocumentSummaryIndex` (already deferred to v2+)
- DSPy integration (deferred until ≥50 rated examples)
