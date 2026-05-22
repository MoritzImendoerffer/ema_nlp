# Advanced Retrieval Strategies — Implementation Plan

**Work unit:** `.claude/work/2026-05-22_advanced-retrieval`  
**Date:** 2026-05-22  
**Status:** Planning complete — run `/next` to start RET-001

---

## 1. Project overview and scope

The EMA website has rich document structure that the current flat index ignores:

- Each EMA page contains multiple Q&A accordion items under a common `source_url` and `topic_path`
- Q&A items link to one another via explicit `cross_refs` metadata fields
- Pages are organized into a topic hierarchy (e.g. `/safety/nitrosamines/question-answers`)

The current retrieval stack treats every Q&A as a completely independent flat node. This works for T1 (simple lookup) questions but misses structural information that T2 (scoping), T3 (multi-hop), and T4 (synthesis) questions need.

**This plan adds a retrieval strategy layer** that lets you switch between retrieval mechanisms via a YAML config key — no code changes required to experiment. It also fixes several architectural inconsistencies found during the code review.

### What's in scope

| Deliverable | Benefit |
|---|---|
| Architecture cleanup (naming, dead code) | Removes confusion between "retrieval strategy" and "prompt strategy" |
| Unified retriever factory (`make_retriever`) | Single code path in `run_eval.py`, `run_langsmith_eval.py`, and `app.py` |
| Recursive retrieval (auto cross_ref expansion) | Improves T3 multi-hop without requiring agent tool calls |
| Hierarchical DocumentSummaryIndex | Improves T2/T4 by grouping Q&As by EMA page |
| Adaptive strategy selection | Agents suggest the best retrieval strategy based on past rated interactions |
| Documentation | Makes the system understandable and extensible |

### What remains out of scope (v1 lock)

- LLM-generated document summaries (hierarchical parent text uses metadata, not LLM)
- Sub-question decomposition (separate retrieval per sub-question) — defer to ablation B
- Graph-based retrieval (IDMP/Neo4j) — deferred to v2+
- DSPy optimization of the strategy selector

---

## 2. Current architecture and problems found

### Retrieval code paths (current — three separate paths)

```
app.py ──────────────────── harness.retrieve.retrieve() ──── VectorStoreIndex
                                                              (direct call, hardcoded mode="hybrid")

run_eval.py ─────────────── retrieve_fn closure ────────────  retrieve() + ablation A1/A2/A3 wrappers
                            (bespoke, not reusable)

harness/chains/ ─────────── EMARetriever(BaseRetriever) ──── retrieve()
                            (LangChain adapter, most structured)
```

**Problem:** The three paths diverge. Ablation steps A1/A2/A3 are only wired in `run_eval.py`. The interactive app and the LangSmith chains never benefit from query expansion or topic filtering.

### Identified inconsistencies

1. **Dead code**: `embed.py::dense_retrieve()` returns `(qa_id, score)` pairs — a different signature than everything else which returns `(qa_id, score, metadata)` triples from `retrieve.py::retrieve()`. It is never called outside its own test.

2. **Duplicate agent**: `harness/agents/react_agent.py` (LlamaIndex `ReActAgent`) and `harness/chains/agents/react.py` (LangGraph) are two fully-independent ReAct implementations. The app uses the former; the eval chains use the latter. They diverge on tool descriptions, state handling, and tracing.

3. **Term collision**: The word `"strategy"` means three different things:
   - Prompting style: `"zero_shot"` / `"few_shot"` / `"cot_self"` (in `simple_rag.py`)
   - Agent name: `"react"` / `"crag"` (in agent wrappers)
   - Retrieval mechanism: planned `"flat"` / `"recursive"` / `"hierarchical"` — but not yet used
   
   Output dicts from all chains currently have a `"strategy"` key with inconsistent values that mix these three meanings.

4. **`DocumentSummaryIndex` was decided but never built**: `DECISIONS.md` says "LlamaIndex is the RAG framework because `DocumentSummaryIndex` directly implements the document-tree-with-summaries approach." But the actual index is a flat `VectorStoreIndex`. The hierarchical capability was planned but never implemented.

5. **Config YAML has no retrieval strategy key**: The current `retrieval:` section only has `mode: dense|bm25|hybrid` and `k`. There is no way to configure recursive or hierarchical retrieval without changing code.

### Target architecture (after this plan)

```
YAML config (retrieval.strategy)
        │
        ▼
make_retriever(config, index)     ─── unified factory ───────────────────────────┐
        │                                                                         │
        ├── strategy: flat         → EMARetriever(mode=dense|bm25|hybrid)         │
        ├── strategy: recursive    → RecursiveEMARetriever(base + cross_ref hops) │
        ├── strategy: hierarchical → HierarchicalEMARetriever(page→Q&A drill-down)│
        └── strategy: agentic      → chain registry picks ReAct/CRAG agent        │
                                                                                   │
app.py ─────────────────────────────────────────────────────────────────────────→─┘
run_eval.py ────────────────────────────────────────────────────────────────────→─┘
run_langsmith_eval.py ──────────────────────────────────────────────────────────→─┘
```

---

## 3. Retrieval strategies: design reference

### 3.1 Flat (current baseline)

Standard dense / BM25 / hybrid retrieval over the flat Q&A node index. No changes to node structure.

```yaml
retrieval:
  strategy: flat          # default when key absent
  mode: hybrid            # dense | bm25 | hybrid
  k: 10
```

Best for: T1 lookup questions. Fast. No overhead.

### 3.2 Recursive (cross_ref expansion)

Initial flat retrieval, then automatically follow `cross_refs` metadata for each top-k result. Deduplicates. Appends expanded nodes after the initial results.

```yaml
retrieval:
  strategy: recursive
  mode: hybrid
  k: 10
  recursive:
    max_hops: 1           # 0 = flat; 1 = one expansion round; 2 = two rounds
```

Best for: T3 multi-hop questions. Automates what the ReAct agent's `follow_cross_refs` tool does manually — but without spending LLM tokens. The agent tool still exists for cases requiring more selective traversal.

**Implementation detail**: Max_hops=1 expands each initially retrieved Q&A by its cross_refs. Max_hops=2 then expands *those* results again. Circular references are tracked via a `seen_ids` set.

### 3.3 Hierarchical (DocumentSummaryIndex)

Two-level index: one parent node per `source_url`, children = Q&A pairs from that page. Retrieval:
1. Retrieve top `top_doc_k` parent (page) nodes by dense similarity
2. Expand: pull all child Q&A nodes for each matched parent
3. Re-rank children by dense similarity to original query

```yaml
retrieval:
  strategy: hierarchical
  mode: dense             # mode applies to both parent and child retrieval
  k: 10
  hierarchical:
    top_doc_k: 5          # number of parent pages to expand
    summary_index_dir: ~/Nextcloud/Datasets/ema_nlp/hierarchical_index
```

Best for: T2 scoping questions ("what does the EMA guidance say about X?") where you want all Q&As from the same regulatory page. Also useful for T4 synthesis across an entire EMA document.

**Parent node text** (metadata-derived, no LLM call required):
```
Title: {source_title}
Topic: {topic_path}
Q&A count: {n}
Sample questions: {first 2-3 question texts, truncated}
```

### 3.4 Agentic (ReAct / CRAG)

The existing ReAct and CRAG agents from `harness/chains/agents/`. The agent chooses its own retrieval tools. Configured via the chain registry (`strategy: agentic` routes to a chain in `CHAIN_REGISTRY`).

```yaml
retrieval:
  strategy: agentic
  mode: hybrid            # default mode for the agent's ema_search tool
  k: 10
answer_generation:
  chain: react            # which chain to use: react | crag
```

Best for: T3/T4 when the agent should decide how many hops to follow and which topics to filter.

### 3.5 Adaptive (strategy selection from rated trajectories)

At query time, `StrategySelector.suggest(query_vec, cache)` queries the rating cache:
- Finds past interactions with similar query embeddings (cosine ≥ 0.85)
- Groups by `retrieval_strategy`
- Returns the strategy with the highest weighted-average rating (weight = embedding similarity)
- Falls back to `"flat"` if fewer than 3 supporting rated examples

This is the "gold standard" goal: the system learns which retrieval pattern works best for which question patterns, based on user feedback.

---

## 4. Task execution plan

### Critical path

```
RET-001 (cleanup)
    └── RET-002 (config schema)
            ├── RET-003 (recursive)   ─┐
            ├── RET-004 (hierarchical) ─┤─── RET-006 (integration) ─── RET-007 (docs)
            └── RET-005 (adaptive)    ─┘
```

### Task summary table

| Task | Title | Hours | Type | Depends on |
|------|-------|-------|------|-----------|
| RET-001 | Architecture cleanup | 2h | foundation | — |
| RET-002 | Config schema + factory | 3h | foundation | RET-001 |
| RET-003 | Recursive retrieval | 3h | feature | RET-002 |
| RET-004 | Hierarchical index | 4h | feature | RET-002 |
| RET-005 | Adaptive strategy selection | 3h | feature | RET-002 |
| RET-006 | Eval + chain registry integration | 2h | integration | RET-003, RET-004, RET-005 |
| RET-007 | Documentation | 3h | documentation | all |
| **Total** | | **20h** | | |

---

## 5. Config schema reference (after implementation)

Full YAML schema for the `retrieval:` section:

```yaml
retrieval:
  strategy: flat              # flat | recursive | hierarchical | agentic
  mode: hybrid                # dense | bm25 | hybrid  (applies to flat + recursive)
  k: 10                       # top-k results

  # Recursive strategy options
  recursive:
    max_hops: 1               # 0 = flat fallback; max recommended: 2

  # Hierarchical strategy options
  hierarchical:
    top_doc_k: 5              # number of parent pages to retrieve and expand
    summary_index_dir: ~/Nextcloud/Datasets/ema_nlp/hierarchical_index
```

All sub-sections are optional — sensible defaults apply when absent.

---

## 6. Quality assurance

### Test coverage requirements

- RET-003: 4 new tests in `tests/test_retrieval_strategies.py` (recursive — with/without cross_refs, max_hops, circular ref)
- RET-004: 2 new tests (hierarchical — correct parent selection, correct child expansion)
- RET-005: 4 new tests (adaptive — empty cache, single strategy dominant, mixed strategies, below threshold)
- All existing tests must pass throughout (`pytest tests/` green after each task)

### Linting and type checking

```bash
ruff check .          # must pass after each task
mypy harness/         # must pass for new files (existing mypy debt not introduced)
```

### Backward compatibility

- All existing `harness/configs/*.yaml` run unchanged (strategy defaults to `flat`)
- All existing tests pass (output key rename from `strategy` to `prompt_strategy` in RET-001 requires test assertion updates)
- `CacheEntry` loads existing JSON cache files with missing fields defaulting to `None`

---

## 7. Per-question-type strategy recommendations

Once all strategies are implemented, the recommended starting point for each question type:

| Type | Description | Recommended strategy | Why |
|------|-------------|---------------------|-----|
| T1 Lookup | Single fact from one Q&A | `flat` | Fast; retrieval usually hits the right node directly |
| T2 Scoping | "What does EMA say about X?" — coverage across a page | `hierarchical` | Groups all Q&As from the same regulatory page |
| T3 Multi-hop | Follows cross-references between Q&As | `recursive` or `agentic` | Recursive auto-expands; agentic for selective traversal |
| T4 Synthesis | Combines information from multiple sources | `hierarchical` or `agentic` | Hierarchical spans whole pages; agentic can query multiple topics |

After 50+ rated interactions, `adaptive` can be tried — it learns the per-user-question pattern automatically.

---

## 8. Known limitations and future work

1. **Hierarchical parent text is heuristic**: Parent summaries are constructed from metadata (title, topic, Q&A count), not LLM-generated. This is fast and free but may produce less semantically precise parent embeddings. Switch to LLM-generated summaries if T2 metrics don't improve.

2. **Recursive expansion may over-retrieve**: At max_hops=1, a Q&A with many cross_refs (some EMA regulatory guides cross-reference 10+ items) will add many nodes. Consider a `max_expansion` cap (e.g., 20 total nodes including expansions).

3. **Adaptive selector needs 3+ rated examples per strategy**: The 3-example minimum is a soft guard — it prevents overfitting to a single lucky interaction. It also means the selector is silent until meaningful feedback has been collected.

4. **The `harness/agents/react_agent.py` duplication**: The plan only adds a deprecation notice (RET-001). Full migration of `app.py` to use the LangGraph agent from `harness/chains/agents/react.py` is deferred — it requires changes to the Chainlit UI's streaming model.

---

## 9. Next steps after this plan

1. Run `/next` to start `RET-001`
2. After all tasks complete, run the benchmark: `python3 -m harness.run_eval --config harness/configs/retrieval_recursive.yaml`
3. Compare results against `baseline_a0` to measure retrieval strategy impact
4. Use the LangSmith eval (`run_langsmith_eval.py`) to run all strategy × prompt combinations
5. Update `ABLATIONS.md` with observed per-type effects
