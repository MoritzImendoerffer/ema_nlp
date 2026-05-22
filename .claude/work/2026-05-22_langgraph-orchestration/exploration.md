# Exploration — LangGraph Orchestration

## Current state (as of 2026-05-22)

LangGraph is **already in use** — the discovery here is that the stack is closer to the
goal than the question implied. Concretely:

| Layer | What's there | Version |
|---|---|---|
| Retrieval | LlamaIndex VectorStoreIndex + BM25Retriever | llama-index-core 0.14.22 |
| Bridge | `EMARetriever` (LangChain `BaseRetriever`) | harness/chains/retriever.py |
| Orchestration (ReAct) | LangGraph `StateGraph` with 4 tools | langgraph 1.2.1 |
| Orchestration (CRAG) | LangGraph `StateGraph` with grading loop | langgraph 1.2.1 |
| Dispatch | `CHAIN_REGISTRY` (harness/chains/registry.py) | — |
| Tracing | Phoenix OpenInference + LangSmith | — |

**What's missing** relative to the stated goal:

1. **No dedicated summarization node** — generation prompts consume raw doc lists directly.
2. **No review/QA agent as a graph node** — the judge (`harness/judge.py`) runs as
   a separate post-processing step outside any LangGraph graph.
3. **No node reuse across graphs** — `react.py` and `crag.py` each define their own
   retrieve/generate functions inline; summarization or review nodes added to one
   don't carry over to the other.
4. **No compiled-subgraph composition** — LangGraph 1.2.1 supports passing a compiled
   graph as a node (`parent.add_node("child", compiled_child)`) but this isn't used yet.

---

## Architecture options evaluated

### Option A — Flat registry extension (minimal)
Add `summarize_rag` and `review_rag` to `CHAIN_REGISTRY` as standalone graphs.
**Verdict: rejected.** Each strategy is an island; no composition. Adding a review step
to the CRAG strategy means another full copy of the CRAG logic.

### Option B — Multi-agent supervisor pattern
A top-level supervisor graph routes messages to specialist sub-agents
(retrieval agent, summarization agent, QA agent) and collects their outputs.
**Verdict: over-engineered for this use case.** EMA RAG is primarily a sequential
pipeline (retrieve → process → generate → [review]). Dynamic routing is only needed
for tool-calling agents (ReAct). A supervisor adds complexity without observable benefit
for the linear chain strategies.

### Option C — Modular node library + pipeline factory (recommended)
A `harness/chains/nodes/` package exports individual node functions and optional
subgraphs. A `build_pipeline(config)` factory assembles them into a `StateGraph`
and registers the result in `CHAIN_REGISTRY` by name.

**Why this wins:**
- Directly maps to the ablation design: each ablation swaps one node, not the whole graph.
- Node reuse: `summarization_node` can be included in both simple-RAG and CRAG configs.
- The existing `AgentState`/`CRAGState` patterns are unified into one `PipelineState`.
- LangGraph compiled-subgraph support (confirmed working in 1.2.1) means the ReAct
  agent can be embedded as a retrieval sub-agent inside a larger pipeline.

### Option D — LlamaIndex QueryEngine as primary orchestrator
Use LlamaIndex's own `ReActAgent` with added summarization and review tools.
**Verdict: rejected.** The existing `harness/agents/react_agent.py` (LlamaIndex ReAct)
is already deprecated in favour of the LangGraph version. LlamaIndex tracing is via
OpenInference, which is compatible, but keeping two agent frameworks creates confusion.
LangGraph should be the single orchestration layer.

---

## Recommended design

### 1. Shared pipeline state

```python
# harness/chains/pipeline_state.py
class PipelineState(TypedDict):
    question:         str
    docs:             list[Document]          # raw retrieved docs
    summary:          str                     # optional: condensed context
    answer_text:      str
    cited_qa_ids:     list[str]
    trajectory:       list[dict]
    review_score:     float                   # 0.0 if review not run
    review_feedback:  str
    cycle:            int                     # rewrite/review cycle count
    grade:            str                     # "sufficient" | "insufficient"
    prompt_strategy:  str
```

The current `AgentState` (react) and `CRAGState` (crag) collapse into this. Backwards
compatibility: existing wrappers can still expose a narrow output dict.

### 2. Node library  (`harness/chains/nodes/`)

**`retrieval.py`** — wraps `EMARetriever.invoke()`; returns `{"docs": [...]}`
No change to LlamaIndex or `EMARetriever` — node is a thin adapter.

**`summarization.py`** — new node:
```
docs → LLM prompt (system_summarize.md) → summary string
```
Input: `state["docs"]`, `state["question"]`
Output: `{"summary": str}`
The generated summary is a focused, citation-tagged prose block that the generation
node uses instead of (or alongside) the raw doc list. This compresses token usage
for frontier model calls on large k values.

**`generation.py`** — wraps current `simple_rag` LCEL chains; picks context from
`state["summary"]` (if non-empty) or `state["docs"]` (fallback).

**`review.py`** — new node wrapping `harness/judge.py` logic:
```
answer_text + docs → judge LLM → {"review_score": float, "review_feedback": str}
```
Routing: if `review_score < threshold`, increment `cycle` and route to `rewrite_query`
(reusing the CRAG rewrite node) or to `generation` for a revision. Cap at 2 cycles.

**`grade.py`** — extracted from `crag.py` (doc sufficiency grading); reusable.

**`rewrite.py`** — extracted from `crag.py` (query rewriting); reusable.

### 3. Pipeline factory

```python
# harness/chains/pipeline.py

@dataclass
class PipelineConfig:
    retrieval_strategy: str = "flat"      # maps to EMARetriever config
    retrieval_mode:     str = "hybrid"
    k:                  int = 10
    use_summarization:  bool = False
    use_grade:          bool = False      # CRAG-style doc grading
    use_review:         bool = False      # post-gen QA review
    max_cycles:         int = 2
    prompt_strategy:    str = "zero_shot"
    use_react_agent:    bool = False      # embed ReAct as retrieval subgraph

def build_pipeline(config: PipelineConfig, *, retriever, llm) -> compiled_graph:
    ...
```

Named pipeline configs registered in `CHAIN_REGISTRY`:

| Name | Phases |
|---|---|
| `simple_rag_zero` | retrieve → generate |
| `simple_rag_few` | retrieve → generate (few-shot) |
| `simple_rag_cot` | retrieve → generate (CoT) |
| `summarize_rag` | retrieve → summarize → generate |
| `crag` | retrieve → grade → [rewrite] → generate |
| `crag_review` | retrieve → grade → [rewrite] → generate → review → [revise] |
| `react` | react_subgraph → extract |
| `react_review` | react_subgraph → extract → review |

### 4. LlamaIndex memory integration

**Short recommendation: defer to v2+ for LlamaIndex memory in the pipeline.**

The current setup already has two memory layers:
- `harness/query_cache.py` — FAISS semantic cache for deduplicating queries (v1 ✓)
- Phoenix annotations — rated trajectory store for few-shot injection (v1 ✓)

LlamaIndex's `ChatMemoryBuffer` or `VectorMemory` would add:
- Conversation history within a session (multi-turn Q&A)
- Cross-session memory recall

These are only meaningful for interactive app use, not for the benchmark eval loop
(which is always single-turn). For the app, the cleanest approach when the time comes
is to keep LlamaIndex memory as a tool exposed to the ReAct agent, not as pipeline
state — this avoids contaminating eval runs.

**LangGraph `MemorySaver`** is the right mechanism for session checkpointing in `app.py`
(saves/restores graph state between turns in an interactive session). It is orthogonal
to LlamaIndex memory and does not affect eval runs (which use `thread_id=None`).

### 5. How to iterate quickly

The factory pattern means new strategies are config, not code:

```python
# Register a new strategy in one line
CHAIN_REGISTRY["crag_summarize_review"] = lambda r, l, **kw: build_pipeline(
    PipelineConfig(use_grade=True, use_summarization=True, use_review=True),
    retriever=r, llm=l,
)
```

To add a new **node type** (e.g. a reranker node, or a metadata-filter node):
1. Add a function to `harness/chains/nodes/`
2. Add a field to `PipelineConfig`
3. Wire it into `build_pipeline()`

No existing graphs are touched.

---

## Implementation plan

### Task LG-001 — PipelineState + node library scaffold
- Create `harness/chains/pipeline_state.py` with the unified `PipelineState` TypedDict
- Create `harness/chains/nodes/__init__.py` (empty)
- Extract `grade_relevance` and `rewrite_query` from `crag.py` into `nodes/grade.py`
  and `nodes/rewrite.py` (no behaviour change, just factored out)
- Estimated effort: 1–2h

### Task LG-002 — Summarization node
- Create `harness/chains/nodes/summarization.py`
- Create `harness/prompts/system_summarize.md`
- Add `summarize_rag` to `CHAIN_REGISTRY`
- Tests: mock LLM, verify summary appears in output dict
- Estimated effort: 1–2h

### Task LG-003 — Review node + review loop
- Create `harness/chains/nodes/review.py` wrapping `harness/judge.py`
- Add `crag_review` and `react_review` to `CHAIN_REGISTRY`
- Tests: mock judge, verify cycle cap is respected
- Estimated effort: 2–3h

### Task LG-004 — `build_pipeline()` factory
- Create `harness/chains/pipeline.py` with `PipelineConfig` and `build_pipeline()`
- Rewrite `CHAIN_REGISTRY` entries for `simple_rag_*` and `crag` to use `build_pipeline()`
  (keeping `react` using its own graph because the tool-call loop is structurally different)
- Estimated effort: 2–3h

### Task LG-005 — LangGraph MemorySaver for `app.py` (interactive sessions)
- Wire `MemorySaver` into `app.py`'s agent graph call with `thread_id=session_id`
- Keeps eval runs unaffected (no `thread_id` → no checkpointing)
- Estimated effort: 1h (only app.py changes)

---

## Key risks

1. **Shared mutable state in `_last_docs`** — the ReAct agent already has a note about
   this. Moving to `PipelineState` (which carries `docs` as a state field) eliminates
   the side-channel mutable list. LG-001 should fix this as part of the refactor.

2. **Review loop latency** — adding a judge LLM call per answer doubles latency in
   `crag_review`. The review node should be skipped unless explicitly configured
   (`use_review=True`). Benchmark configs should default to `use_review=False`.

3. **Prompt token growth with summarization** — if `use_summarization=True` but the
   summary is not significantly shorter than the raw docs, it wastes a LLM call.
   Measure on 10 benchmark questions before enabling by default.

4. **Subgraph state schema alignment** — passing the ReAct compiled subgraph as a node
   inside a `PipelineState` graph requires the subgraph's output keys to match what the
   parent expects. The current `_AgentWrapper` output dict already has `answer_text`,
   `cited_qa_ids`, `trajectory`, `docs` — these map cleanly to `PipelineState`.

---

## Decision: additive approach (clean break deferred as LG-008)

Tests in `tests/test_langchain_chains.py` import directly from `simple_rag.py` and
`crag.py`. The additive approach keeps all existing tests passing, delivers new
functionality (summarize_rag, crag_review, react_review, RLHF extension) without
regression risk, and defers the clean-break migration to LG-008 once the factory is
validated on new strategies.

See `implementation-plan.md` for the full task breakdown and clean break vs additive
trade-off analysis.
