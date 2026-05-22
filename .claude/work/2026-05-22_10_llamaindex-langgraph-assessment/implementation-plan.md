# Implementation Plan: Drop LangChain, adopt LlamaIndex Workflows

**Work unit:** 2026-05-22_10_llamaindex-langgraph-assessment  
**Estimated total:** ~27 hours across 11 tasks  
**Goal:** Eliminate all LangChain/LangGraph/LangSmith dependencies. Replace `harness/chains/` with `harness/workflows/` using native LlamaIndex Workflows. Keep Phoenix tracing as the sole observability layer.

---

## Scope

### What is replaced

| Old | New |
|-----|-----|
| `harness/chains/` (entire directory) | `harness/workflows/` |
| `harness/chains/llms.py` → `ChatAnthropic`, `ChatOpenAI` | `harness/llms.py` → LlamaIndex `Anthropic`, `OpenAILike` |
| `harness/chains/registry.py` → `get_chain()` | `harness/workflows/registry.py` → `get_workflow()` |
| LangGraph `StateGraph` + `PipelineState` TypedDict | LlamaIndex `Workflow` + typed `Event` subclasses |
| LangGraph `MemorySaver` in `app.py` | Per-request Workflow invocation (no cross-turn graph state) |
| `harness/langsmith_dataset.py` | Deleted |
| `harness/run_langsmith_eval.py` | Deleted |
| `harness/agents/react_agent.py` | Deleted (already deprecated) |

### What is NOT touched

- `harness/embed.py`, `harness/embed_hierarchical.py` — LlamaIndex index building, unchanged
- `harness/retrieve.py` — retrieval facade (flat, recursive, hierarchical, RRF), unchanged  
  **Key change:** workflows call `retrieve_with_config()` directly — no `EMARetriever` bridge needed
- `harness/providers.py` — LlamaIndex Settings config, unchanged
- `harness/judge.py` — uses direct Anthropic SDK, unchanged
- `harness/answer_gen.py` — uses `harness.models.call_model`, unchanged
- `harness/run_eval.py` — uses `answer_gen.py` and direct retrieval, zero LangChain imports already
- `harness/query_cache.py`, `harness/models.py`, `harness/fewshot_inject.py` — unchanged
- `harness/ablations/` — unchanged
- All other tests — unchanged

---

## Architecture: Before and After

### Before (LangGraph)

```
app.py
  └── _build_session_pipeline()
        ├── EMARetriever(index)           [langchain BaseRetriever wrapping LlamaIndex]
        ├── ChatAnthropic(model)          [langchain_anthropic]
        └── build_pipeline(PipelineConfig, retriever, llm, checkpointer=MemorySaver())
              └── LangGraph StateGraph
                    ├── retrieval_node    [calls retriever.invoke()]
                    ├── grade_node        [calls LLM with ChatPromptTemplate | StrOutputParser]
                    ├── rewrite_node
                    ├── summarization_node
                    ├── generation_node
                    └── review_node       [calls Judge]
```

### After (LlamaIndex Workflows)

```
app.py
  └── _build_session_workflow()
        ├── index (LlamaIndex VectorStoreIndex — same as before)
        ├── llm = get_llm("mid")          [harness/llms.py → LlamaIndex Anthropic]
        └── get_workflow("crag", index, llm)
              └── CRAGWorkflow(Workflow)
                    ├── retrieve_step()   [calls retrieve_with_config() directly]
                    ├── grade_step()      [LlamaIndex LLM structured output]
                    ├── rewrite_step()
                    └── generate_step()  [LlamaIndex LLM]
```

**The EMARetriever bridge is eliminated.** Workflows call `retrieve_with_config()` (in `harness/retrieve.py`) directly, passing the LlamaIndex index object that workflows hold as an attribute.

---

## New package structure

```
harness/
├── llms.py                      NEW — LlamaIndex LLM factory (replaces chains/llms.py)
├── workflows/
│   ├── __init__.py
│   ├── events.py                NEW — typed Pydantic Event subclasses
│   ├── utils.py                 NEW — format_docs, load_system_prompt, extract_answer
│   ├── simple_rag.py            NEW — SimpleRAGWorkflow (zero/few/cot variants)
│   ├── crag.py                  NEW — CRAGWorkflow (grade/rewrite loop)
│   ├── summarize_rag.py         NEW — SummarizeRAGWorkflow
│   ├── review.py                NEW — review step + ReviewMixin
│   ├── react.py                 NEW — ReAct agent (FunctionAgent + Workflow wrapper)
│   ├── composites.py            NEW — CRAGSummarize, CRAGReview, ReactReview workflows
│   └── registry.py              NEW — get_workflow(), list_workflows()
└── chains/                      DELETED after WF-009 is complete
```

---

## Event types (harness/workflows/events.py)

```python
from llama_index.core.workflow import Event

class RetrievedEvent(Event):
    docs: list[dict]          # list of {qa_id, score, text, metadata} dicts

class InsufficientEvent(Event):
    query: str                # rewritten query for next retrieval attempt
    cycle: int

class GradedEvent(Event):     # internal — grade step emits one of these two
    docs: list[dict]
    grade: str                # "sufficient" | "insufficient"

class SummarizedEvent(Event):
    docs: list[dict]
    summary: str

class GeneratedEvent(Event):
    answer_text: str
    docs: list[dict]
    prompt_strategy: str
    cited_qa_ids: list[str]

class ReviewedEvent(Event):
    answer_text: str
    docs: list[dict]
    review_score: float
    review_feedback: str
    passed: bool
```

---

## Uniform output contract

Every workflow's `StopEvent.result` is a dict with at minimum:

```python
{
    "answer_text": str,           # the generated answer
    "docs": list[dict],           # retrieved docs (qa_id, score, text, metadata)
    "prompt_strategy": str,       # e.g. "zero_shot", "crag", "react"
}
```

Optional per-strategy keys: `summary`, `rewrite_cycles_used`, `review_score`, `review_feedback`, `trajectory`, `cited_qa_ids`.

The registry's `get_workflow()` returns a wrapper with:
- `.invoke({"question": str, "few_shot_context": str}) -> dict`  (sync, via `asyncio.run()`)
- `.ainvoke({"question": str, "few_shot_context": str}) -> dict` (async)

---

## Dependency changes (pyproject.toml)

### Add

```toml
"llama-index-llms-openai>=0.3",   # OpenAILike for Together AI via OpenAI-compatible API
```

### Remove

```toml
# ALL of these go away:
"langchain-core>=0.3",
"langchain-anthropic>=0.3",
"langchain-openai>=0.2",
"langchain-community>=0.3",
"langgraph>=0.2",
"langsmith>=0.2",
```

Note: `anthropic>=0.100` stays (used by `judge.py` and `harness/models.py`).

---

## Task execution plan

### Phase 1 — Foundation (do first, no parallelism possible)

| Task | Est. | Output |
|------|------|--------|
| WF-001 | 2h | `harness/llms.py` |
| WF-002 | 2h | `harness/workflows/__init__.py`, `events.py`, `utils.py` |

### Phase 2 — Core Workflows (parallel; all depend on WF-001+WF-002)

| Task | Est. | Output |
|------|------|--------|
| WF-003 | 3h | `simple_rag.py` |
| WF-004 | 3h | `crag.py` |
| WF-005 | 2h | `summarize_rag.py` |
| WF-006 | 2h | `review.py` |
| WF-007 | 4h | `react.py` |

WF-011 (tests) can be written in parallel with Phase 2.

### Phase 3 — Integration (sequential)

| Task | Est. | Output |
|------|------|--------|
| WF-008 | 3h | `composites.py`, `registry.py` |
| WF-009 | 2h | `app.py` updated |
| WF-010 | 1h | `harness/chains/` deleted, `pyproject.toml` stripped |

---

## LangSmith drop: what is lost and how to compensate

| Lost | Replacement |
|------|-------------|
| LangSmith dataset upload | N/A — benchmark JSONL is the dataset |
| LangSmith batch eval runner (`run_langsmith_eval.py`) | `run_eval.py` already handles batch eval natively |
| LangSmith side-by-side comparison UI | Phoenix experiment comparison (per-span tags per run_id) |
| Automatic LangChain auto-tracing | Phoenix `openinference-instrumentation-llama-index` (already in place) |

No functionality from `run_eval.py` is lost. Only `run_langsmith_eval.py` is deleted.

---

## Risk notes

1. **Async-first:** LlamaIndex Workflows require `async def` steps. Sync entry points (`run_eval.py`) need `asyncio.run()` wrappers. This is straightforward but must be applied consistently.

2. **Session memory in app.py:** LangGraph's MemorySaver provided cross-turn checkpointing within a browser session. After migration, each turn is an independent Workflow invocation. The few-shot context (selected from query cache) is still injected per-turn. If conversational context tracking within the pipeline is needed, it must be maintained at the app.py level (e.g., storing previous Q&A pairs in `cl.user_session`).

3. **Phoenix tracing:** `openinference-instrumentation-llama-index` instruments Workflow steps automatically. Verify spans appear in Phoenix after first workflow invocation.

4. **Together AI via OpenAILike:** LlamaIndex's `OpenAILike` accepts `api_base` and `api_key`. Test with a real Together API call before WF-001 is marked complete.

---

## Next step

Run `/next` to start WF-001.
