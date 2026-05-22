# Implementation Plan — LangGraph Orchestration

## Goals (restated from user input)

1. **Strategy comparison** — test RAG approaches from basic to advanced via a common interface
2. **User-controlled pipeline** — inspect traces, then adjust retrieval/summarization parameters for a specific run
3. **RLHF feedback loop** — rate individual agent thinking steps; have those ratings influence future runs (few-shot injection)

---

## Architecture overview

```
                         QUERY
                           │
                           ▼
              ┌────────────────────────┐
              │     CHAIN_REGISTRY     │
              │  get_chain(name, ...)  │
              └────────────┬───────────┘
                           │
              ┌────────────▼────────────────────────────────────────────┐
              │  LangGraph StateGraph  (PipelineState)                  │
              │                                                         │
              │  Strategies (registered by name):                       │
              │                                                         │
              │  simple_rag_zero   retrieve → generate                  │
              │  simple_rag_few    retrieve → generate (few-shot)       │
              │  simple_rag_cot    retrieve → generate (CoT)            │
              │  summarize_rag     retrieve → summarize → generate      │
              │  crag              retrieve → grade ⇄ rewrite           │
              │                           → generate                   │
              │  crag_summarize    retrieve → grade ⇄ rewrite           │
              │                           → summarize → generate        │
              │  crag_review       crag → generate → review ⇄ revise   │
              │  react             react_subgraph → extract             │
              │  react_review      react_subgraph → extract → review    │
              └────────────────────────────────────────────────────────┘
                           │  named node spans
                           ▼
              Phoenix traces  +  LangSmith runs
                           │
                           ▼
              User inspects trace → rates span (rating.py)
                           │  annotation stored in Phoenix
                           ▼
              fewshot_inject fetches top-rated node examples
                           │  injected into node prompt for next run
                           ▼
                       better answers
```

### Core data flow (PipelineState)

```python
class PipelineState(TypedDict):
    # Input
    question:          str
    few_shot_context:  str          # pre-injected by fewshot_inject

    # Retrieval
    docs:              list[Document]

    # Optional summarization
    summary:           str          # empty = not yet run

    # Generation
    answer_text:       str
    cited_qa_ids:      list[str]
    trajectory:        list[dict]   # ReAct: tool steps; pipeline: node steps
    prompt_strategy:   str

    # Review/correction loops
    review_score:      float        # 0.0 = review not run
    review_feedback:   str
    rewrite_cycle:     int          # CRAG query-rewrite cycles
    review_cycle:      int          # post-gen revision cycles
    grade:             str          # "sufficient" | "insufficient"
```

All strategies share this schema. The nodes read from and write to it; nodes that are
not included in a strategy simply leave their fields at their default values.

---

## Clean break vs additive — the trade-off

This is the key architectural decision. Here is what each means in practice:

### Additive (recommended for now)

Keep existing `simple_rag_*` and `crag` implementations unchanged.  Add new strategies
(`summarize_rag`, `crag_summarize`, `crag_review`, `react_review`) using the new
`build_pipeline()` factory and `PipelineState`.

```
CHAIN_REGISTRY
├── simple_rag_zero   → simple_rag.py (LCEL, unchanged)
├── simple_rag_few    → simple_rag.py (LCEL, unchanged)
├── simple_rag_cot    → simple_rag.py (LCEL, unchanged)
├── crag              → crag.py (LangGraph, unchanged)
├── react             → react.py (LangGraph, unchanged)
│
├── summarize_rag     → build_pipeline() ← NEW
├── crag_summarize    → build_pipeline() ← NEW
├── crag_review       → build_pipeline() ← NEW
└── react_review      → build_pipeline() ← NEW
```

**Benefits:**
- Zero regression risk — no existing tests break
- New functionality is immediately available
- Incremental: can validate the new factory before touching old code

**Costs:**
- Two code paths (LCEL for simple_rag, LangGraph for new strategies)
- LCEL chains produce coarser LangSmith spans than LangGraph node spans
- Technical debt: eventually needs unifying

**When does the cost matter?** Only if you want per-node RLHF annotation for `simple_rag_zero`
(e.g., "the retrieval step in this simple_rag run was bad"). For simple_rag there are no
agent decisions to annotate — just a fixed retrieve → generate pipeline. RLHF is most
valuable for agentic strategies (react, crag) where the agent makes real decisions.

### Clean break (LG-008, deferred)

Migrate `simple_rag_*` and `crag` to use `build_pipeline()`.
CHAIN_REGISTRY names stay the same; only internal implementation changes.

```
CHAIN_REGISTRY
├── simple_rag_zero   → build_pipeline(PipelineConfig(strategy="zero_shot")) ← migrated
├── simple_rag_few    → build_pipeline(PipelineConfig(strategy="few_shot"))  ← migrated
├── simple_rag_cot    → build_pipeline(PipelineConfig(strategy="cot_self"))  ← migrated
├── crag              → build_pipeline(PipelineConfig(use_grade=True))       ← migrated
├── react             → react.py (kept as-is, structurally different)
│
├── summarize_rag     → build_pipeline()
├── crag_summarize    → build_pipeline()
├── crag_review       → build_pipeline()
└── react_review      → build_pipeline()
```

**Benefits over additive:**
- Single code path for all linear/semi-linear strategies
- Per-node LangGraph spans for `simple_rag_*` (better observability, richer RLHF)
- Cleaner mental model

**Costs:**
- `test_langchain_chains.py` tests that import from `simple_rag.py`/`crag.py` directly
  need updating (around 15 tests, mechanical changes)
- More upfront risk before new functionality is tested

**Recommendation:** Start with additive (LG-001–LG-007). Schedule clean break as optional
LG-008 after the factory is validated on new strategies.

---

## The RLHF feedback loop

The current loop (already implemented) works for the ReAct agent:

```
1. ReAct agent runs → Phoenix trace created (root span + TOOL child spans)
2. User rates answer via rating.py → annotation stored on root span in Phoenix
3. fewshot_inject.get_fewshot_context() fetches top-rated trajectories by similarity
4. Formatted trajectory injected into ReAct agent's system prompt for next run
```

**Extension needed for pipeline strategies (LG-006):**

The same loop should work for pipeline node steps — specifically the key decision points
in CRAG/review pipelines:

```
1. Pipeline runs → LangGraph nodes appear as named spans in Phoenix/LangSmith
2. User rates specific node span (e.g., "this grade was wrong, docs WERE sufficient")
   via `rating.py --span-name grade`
3. fewshot_inject fetches top-rated examples for that specific node
4. Examples injected into that node's prompt template ({few_shot_examples} slot)
```

This requires:
- Node prompts that include a `{few_shot_examples}` slot (injected before pipeline starts)
- Phoenix span annotations on child spans (not just root)
- `get_fewshot_context()` extended with optional `node_name` filter

Note: the RLHF loop is most valuable for nodes that make **decisions** (grade, rewrite,
generate). It is not meaningful for the retrieval node (which is deterministic given the
config) or the summarization node (which has no branching).

---

## Node library design (`harness/chains/nodes/`)

Each node is a Python function with signature:
```python
def node_name(state: PipelineState) -> dict[str, Any]:
    ...
```
The return dict is a partial `PipelineState` update (only the keys the node modifies).

| Node | Input keys | Output keys | LLM call? |
|---|---|---|---|
| `retrieval` | question | docs | No |
| `grade` | question, docs | grade | Yes |
| `rewrite` | question, rewrite_cycle | question, rewrite_cycle | Yes |
| `summarization` | question, docs | summary | Yes |
| `generation` | question, docs/summary, few_shot_context | answer_text, cited_qa_ids, prompt_strategy | Yes |
| `review` | question, answer_text, docs | review_score, review_feedback, review_cycle | Yes |

Routing functions (pure Python, no LLM):
```python
def route_after_grade(state) -> str:   # "generate" | "rewrite"
def route_after_review(state) -> str:  # "end" | "revise"
def route_after_agent(state) -> str:   # "tools" | "end" | "extract"
```

---

## Pipeline factory

```python
@dataclass
class PipelineConfig:
    # Retrieval
    retrieval_strategy: str = "flat"    # "flat" | "recursive" | "hierarchical"
    retrieval_mode:     str = "hybrid"  # "dense" | "bm25" | "hybrid"
    k:                  int = 10

    # Phases to include (bool flags)
    use_grade:          bool = False    # CRAG-style doc sufficiency check
    use_summarization:  bool = False    # condense docs before generation
    use_review:         bool = False    # post-gen faithfulness + correctness check

    # Loops
    max_rewrite_cycles: int = 2         # max CRAG query-rewrite iterations
    max_review_cycles:  int = 1         # max answer-revision iterations after review

    # Prompt configuration
    prompt_strategy:    str = "zero_shot"  # "zero_shot" | "few_shot" | "cot_self"
    review_threshold:   float = 0.6     # review_score below this triggers revision

    # Few-shot injection (RLHF)
    few_shot_enabled:   bool = False    # whether to inject fewshot context at run time
```

Usage:
```python
# One-liner for a new strategy:
CHAIN_REGISTRY["crag_summarize_review"] = lambda r, l, **kw: build_pipeline(
    PipelineConfig(use_grade=True, use_summarization=True, use_review=True),
    retriever=r, llm=l,
)
```

---

## Task breakdown

### LG-001 — Pipeline foundation: PipelineState + node scaffold (2–3h)

**Scope:**
- Create `harness/chains/pipeline_state.py` with `PipelineState` TypedDict and
  `make_initial_state(question, few_shot_context="") -> PipelineState`
- Create `harness/chains/nodes/__init__.py`
- Create `harness/chains/nodes/retrieval.py`: thin adapter over `EMARetriever.invoke()`
- Create `harness/chains/nodes/generation.py`: wraps `simple_rag.py` prompt chains;
  picks `state["summary"]` if non-empty, else formats `state["docs"]`

**Acceptance criteria:**
- `PipelineState` importable; all fields have documented defaults
- `make_initial_state("test question")` returns a valid state dict
- `retrieval_node(state, retriever)` returns `{"docs": [...]}`
- `generation_node(state, llm, strategy)` returns `{"answer_text": ..., "cited_qa_ids": [...]}`
- Tests in `tests/test_pipeline_nodes.py` with mock retriever and mock LLM

**Dependencies:** None

---

### LG-002 — Extracted CRAG nodes: grade + rewrite (1–2h)

**Scope:**
- Create `harness/chains/nodes/grade.py` with `build_grade_node(llm)` factory
  (extracted from `crag.py`; identical behaviour)
- Create `harness/chains/nodes/rewrite.py` with `build_rewrite_node(llm)` factory
  (extracted from `crag.py`; identical behaviour)
- Update `crag.py` to import from `nodes/` (no behaviour change)
- Rename `cycle` → `rewrite_cycle` in `CRAGState` and wrapper output so it doesn't
  clash with the new `review_cycle` field

**Acceptance criteria:**
- All existing `TestCRAG` tests still pass (`pytest tests/test_langchain_chains.py::TestCRAG`)
- `result["correction_cycles"]` still present in crag output (wrapper maps `rewrite_cycle`)
- `nodes/grade.py` and `nodes/rewrite.py` exportable and callable standalone

**Dependencies:** LG-001

---

### LG-003 — Summarization node (2–3h)

**Scope:**
- Create `harness/chains/nodes/summarization.py` with `build_summarization_node(llm)`
- Create `harness/prompts/system_summarize.md`:
  - Input: question + list of retrieved passages (Q&A pairs with qa_ids)
  - Output: focused 2–4 paragraph summary preserving citation qa_ids in brackets
  - Constraint: must be shorter than the combined raw passages to justify the LLM call
- New strategy `summarize_rag` added to `CHAIN_REGISTRY`
  (retrieve → summarize → generate, no grade loop)

**Acceptance criteria:**
- `summarization_node(state, llm)` returns `{"summary": str}` with citation tags intact
- `list_chains()` includes `"summarize_rag"`
- `get_chain("summarize_rag", ...).invoke({"question": ...})` returns `answer_text`
- Test: mock LLM returns a short string; verify `state["summary"]` is populated and
  `state["answer_text"]` uses the summary (not raw docs) as context

**Dependencies:** LG-001

---

### LG-004 — `build_pipeline()` factory (3–4h)

**Scope:**
- Create `harness/chains/pipeline.py` with `PipelineConfig` dataclass and `build_pipeline()`
- `build_pipeline()` assembles a `StateGraph` from node functions based on `PipelineConfig`
  flags; returns a compiled graph wrapped in a `_PipelineWrapper` (same invoke/ainvoke
  interface as existing wrappers)
- Register the following new strategies in `CHAIN_REGISTRY`:
  - `crag_summarize`: retrieve → grade ⇄ rewrite → summarize → generate
  - All existing `simple_rag_*` and `crag` entries remain unchanged (additive approach)
- `PipelineConfig` is YAML-serializable (all fields are primitives) so run configs can
  specify it inline:

  ```yaml
  chain:
    name: build_pipeline
    config:
      use_grade: true
      use_summarization: true
      k: 15
      prompt_strategy: cot_self
  ```

**Acceptance criteria:**
- `build_pipeline(PipelineConfig(), retriever=r, llm=llm).invoke({"question": "..."})` returns
  standard output dict with `answer_text`, `docs`, `cited_qa_ids`, `prompt_strategy`
- `crag_summarize` strategy in CHAIN_REGISTRY passes same smoke test as `crag`
- Tests cover: no-grade linear path, grade-rewrite loop bounded by `max_rewrite_cycles`,
  summarization included when `use_summarization=True`
- All previously passing tests still pass (additive, no breakage)

**Dependencies:** LG-001, LG-002, LG-003

---

### LG-005 — Review node + review strategies (2–3h)

**Scope:**
- Create `harness/chains/nodes/review.py` with `build_review_node(llm, threshold)`
  wrapping `harness/judge.py` logic:
  - Calls `Judge.faithfulness(question, answer, context)` and
    `Judge.correctness(question, answer, gold_answer="")` (gold unknown at run time → omit)
  - Converts 1–5 scores to `review_score` in [0, 1]
  - Stores `review_feedback` from judge reasons
  - Returns `{"review_score": float, "review_feedback": str, "review_cycle": int}`
- Routing: `route_after_review(state)` → `"end"` if `review_score >= threshold` or
  `review_cycle >= max_review_cycles`, else `"revise"` (back to generation node)
- Register new strategies:
  - `crag_review`: crag + review loop (retrieve → grade ⇄ rewrite → generate → review ⇄ revise)
  - `react_review`: react subgraph + review node
- Note: review uses faithfulness only (no gold answer at run time); the full
  faithfulness+correctness judge pair is used by `run_eval.py` offline — keep the two uses distinct

**Acceptance criteria:**
- `review_node(state, llm, threshold)` returns `{"review_score": float, "review_feedback": str}`
- Review cycle cap: invoking `crag_review` with always-low judge mock never loops > `max_review_cycles`
- `react_review` strategy invokeable (mock react subgraph + mock judge)
- Existing `TestEvaluators` tests unaffected (judge.py unchanged)

**Dependencies:** LG-001, LG-004

---

### LG-006 — Per-step RLHF feedback extension (2–3h)

**Scope:**
- Extend `harness/rating.py` with `--span-name NODE_NAME` option:
  - When supplied, annotates the named child span (e.g., `grade`, `rewrite`, `generate`)
    in addition to (or instead of) the root span
  - Useful for "this grade node was wrong" or "this rewrite was good"
- Extend `harness/fewshot_inject.py` with `node_name: str | None = None` parameter:
  - When `node_name` is supplied, fetches Phoenix spans filtered by `span.name == node_name`
  - Formats node-specific examples (input state + output state for that node)
  - Returns a few-shot prefix for that node's prompt
- Add `{few_shot_examples}` slot to `system_summarize.md` and generation prompts for pipeline
  strategies so node-level injection works
- Update `build_pipeline()` to accept a `fewshot_context_by_node: dict[str, str]` parameter
  that pre-fills the prompt slot for each specified node

**Acceptance criteria:**
- `get_fewshot_context(query_vec, cache, node_name="grade")` returns examples filtered to
  grade-node spans (mock Phoenix response)
- `rating.py --span-name generate` successfully annotates a child span (mock Phoenix client)
- `build_pipeline(..., fewshot_context_by_node={"generate": "..."})` injects the context
  into the generation node's prompt
- Existing `get_fewshot_context()` calls without `node_name` continue to work (backward compat)

**Dependencies:** LG-004, LG-005

---

### LG-007 — LangGraph MemorySaver for interactive sessions (1h)

**Scope:**
- Wire `MemorySaver` into `app.py` for multi-turn interactive Q&A:
  - `compiled_graph = pipeline.compile(checkpointer=MemorySaver())`
  - Pass `config={"configurable": {"thread_id": session_id}}` in interactive mode
  - Eval runs pass no `thread_id` (stateless; no checkpointing overhead)
- Session ID: derived from `str(uuid.uuid4())` at app startup, printed to console
- Enables: "follow-up question" without re-asking the original context

**Acceptance criteria:**
- `app.py` interactive mode creates a session ID and uses `MemorySaver`
- Eval scripts (`run_eval.py`, `run_langsmith_eval.py`) invoke pipelines without `thread_id`
- Unit test: two sequential `graph.invoke()` calls with the same `thread_id` share state

**Dependencies:** LG-004

---

### LG-008 (optional) — Clean break: migrate simple_rag_* to build_pipeline() (2–3h)

**Do only if**: the team wants per-node LangGraph spans for `simple_rag_*` strategies,
or two code paths become a maintenance burden.

**Scope:**
- Replace `_build_simple_rag_zero/few/cot` in `registry.py` with `build_pipeline(PipelineConfig(...))`
- Remove or deprecate `harness/chains/simple_rag.py` (keep `extract_answer` and `format_docs`
  as utilities imported by `nodes/generation.py`)
- Update `tests/test_langchain_chains.py::TestBuildRagChain` to test `build_pipeline()` directly
- `TestChainRegistry.test_list_chains_returns_all_strategies` updated to include new strategies

**Acceptance criteria:**
- All existing `simple_rag_*` output keys unchanged (`answer_text`, `docs`, `prompt_strategy`)
- Full test suite passes
- `simple_rag_zero` now shows as three named node spans in LangSmith (retrieve/generate/extract)

**Dependencies:** LG-004

---

## File structure after all tasks

```
harness/chains/
├── __init__.py
├── agents/
│   ├── crag.py          # unchanged (grade/rewrite imported from nodes/)
│   └── react.py         # unchanged
├── nodes/               # NEW
│   ├── __init__.py
│   ├── retrieval.py     # LG-001
│   ├── generation.py    # LG-001
│   ├── grade.py         # LG-002
│   ├── rewrite.py       # LG-002
│   ├── summarization.py # LG-003
│   └── review.py        # LG-005
├── pipeline_state.py    # LG-001
├── pipeline.py          # LG-004  (PipelineConfig + build_pipeline)
├── retriever.py         # unchanged
├── registry.py          # updated to include new strategies
├── simple_rag.py        # unchanged (or deprecated in LG-008)
├── llms.py              # unchanged
└── evaluators.py        # unchanged

harness/prompts/
└── system_summarize.md  # LG-003  (NEW)

tests/
├── test_langchain_chains.py  # unchanged (or updated in LG-008)
└── test_pipeline_nodes.py    # LG-001  (NEW)
```

---

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Shared mutable `_last_docs` in react.py | Medium | PipelineState carries `docs` in state; fix in LG-001/LG-004 when embedding react as subgraph |
| Review loop latency (2× LLM call per answer) | High | `use_review=False` by default; eval configs explicitly opt in |
| Summarization doesn't compress: wastes one LLM call | Medium | Benchmark on 10 items before enabling as default; prompt instructs to be concise |
| fewshot_inject Phoenix fallback if server down | Low | Existing `try/except` in _fetch_trajectory handles this; return None → no injection |
| LG-008 test migration risk | Medium | Only do LG-008 after all new tests are green; treat as a separate PR |

---

## Critical path

```
LG-001 (foundation)
    ├─→ LG-002 (grade/rewrite) ──┐
    ├─→ LG-003 (summarization) ──┤
    │                            ▼
    └──────────────────→ LG-004 (factory) ──→ LG-005 (review) ──→ LG-006 (RLHF)
                                                                        │
                         LG-007 (MemorySaver) ◄── LG-004 ──────────────┘

LG-008 (optional clean break): any time after LG-004 is stable
```

Parallel opportunities: LG-002 and LG-003 can be implemented simultaneously.
