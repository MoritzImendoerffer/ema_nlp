# Exploration: RL feedback, semantic cache, and online learning

**Date:** 2026-05-15  
**Updated:** 2026-05-15 (after library research — see revision note at bottom)  
**Phase context:** Phase 1 in progress. LlamaIndex + Phoenix decided. TASK-027 (ReActAgent) not yet built — good timing to lock the data model now.

---

## What the user is asking for

Three connected features:

1. **Trajectory rating** — after a query, the user can rate how well the agent did (the reasoning chain, not just the answer). These ratings become a feedback signal.

2. **Online learning from ratings** — the agent uses past high-rated trajectories on similar questions as few-shot context, so it does not rediscover a good strategy for question types it has already handled well.

3. **Semantic query cache with user confirmation** — before running the full pipeline, show the user the top-k most similar past questions (with their cached answers and ratings). The user chooses: use cached answer, use it as starting context, or trigger fresh full retrieval. The user always has the fresh-retrieval option.

---

## Library research findings (revised design)

An initial design proposed a custom SQLite feedback store. Research into existing libraries changed the approach:

| Library | Verdict |
|---------|---------|
| **GPTCache** | Abandoned since late 2023. LlamaIndex integration is broken (open GitHub issue, unresolved). Skip. |
| **Arize Phoenix** (already chosen) | Has a built-in human annotation API — star ratings and labels attachable to any span or trace via SDK or UI. **Eliminates the need for a separate feedback store entirely.** |
| **Langfuse** | Functionally similar to Phoenix for feedback. Running both would be redundant overhead for a one-developer project. Skip for now. |
| **DSPy** | Batch *compiler*, not a runtime few-shot selector. Takes a labeled dataset offline → outputs a static optimized prompt artifact. The "find top-k similar rated traces at runtime and inject them" step is not what DSPy does — that retrieval still needs custom code. Add DSPy later when ≥50 rated examples exist. |
| **TRL / OpenRLHF** | Weight-update RLHF. Wrong problem. Skip. |
| **mem0 / Zep** | Cross-session conversational memory. Wrong problem. Skip. |
| **LlamaIndex built-ins** | No semantic query cache. Embedding cache only. Feedback: none. |

**Key insight:** Phoenix is already the feedback store. The only custom code needed is the similarity search over past query embeddings and the injection logic.

---

## Revised architecture

### Component 1 — Feedback collection via Phoenix annotations (zero new infrastructure)

Phoenix's annotation API accepts `{span_id, label, score, explanation}` payloads on any trace. This is exactly a trajectory rating.

After each agent run, the CLI presents:

```
Query: "What AI limit applies during CAPA for chronic-use nitrosamines?"

Answer: The AI for chronic-use products during CAPA...

Trajectory (3 steps):
  Step 1: search("CAPA limit chronic nitrosamine") → Q22, Q10, Q8
  Step 2: follow_cross_refs("nitrosamines:Q22") → Q10 (AI = 26.5 ng/day)
  Step 3: answer(cited=["nitrosamines:Q10", "nitrosamines:Q8"])

Rate this answer (1–5, Enter to skip): 4
Note (optional): Good chain traversal, answer complete
Rate individual steps? [y/N]:
```

The rating is posted to Phoenix via its SDK. The full trace is already there (from TASK-020). No separate database.

**Ablation B connection:** TASK-029 requires labeling ~50 trajectory steps. The rating UI above, run on B1 trajectory traces, produces those labels directly through Phoenix. The `export_jsonl()` call (see Component 4) produces `trajectory_labels.jsonl`. No separate labeling workflow needed.

### Component 2 — Semantic query cache (thin FAISS index over past queries)

A secondary FAISS index over embeddings of past queries — separate from the document index. Persisted to `harness/index/query_cache.faiss` alongside the document index.

Flow before each agent run:

```
User submits query
    ↓
Embed query (same BGE-large model — no new dep)
    ↓
Search query_cache.faiss for top-k similar past queries (cosine sim > threshold)
    ↓
If matches found:
    "Similar past questions (choose or press Enter to run fresh):"
      [1] sim=0.94 ★4/5  "What is the AI limit for chronic-use products?"
                          Answer: "The AI for chronic-use products is 26.5 ng/day..."
                          3 steps · run_id: 20260515-142301
      [2] sim=0.87 ★5/5  "What thresholds apply during CAPA for nitrosamines?"
                          4 steps · run_id: 20260515-091847
    [a] Use [1] cached answer
    [b] Use [2] cached answer
    [c] Use [1] as few-shot context, run fresh retrieval
    [d] Run full pipeline (no cache influence)
    ↓
User chooses
```

The query cache index maps each past query embedding to: `{run_id, question_text, answer_summary, rating, cited_qa_ids}`. This metadata is stored as a JSON sidecar (`query_cache.json`) alongside the FAISS index — the same pattern already used for the document index.

Similarity threshold: configurable in YAML (default 0.88). Benchmark runs always use `cache: false` — the cache is for interactive/exploratory use only.

### Component 3 — Runtime few-shot injection

When the agent runs (options c and d above), it retrieves the top-k rated past trajectories for similar questions and injects them into the planning prompt:

```python
def get_fewshot_context(query_vec, k=3, min_rating=4) -> str:
    # 1. Search query_cache.faiss
    # 2. Filter to min_rating
    # 3. Fetch full trajectory from Phoenix API (by run_id)
    # 4. Format as few-shot block
```

This is standard few-shot prompting — no weight updates. Every injected example is traceable (its `run_id` links to a Phoenix trace). Phoenix instrumentation records which examples were injected, making the prompt fully reproducible.

Rating threshold for injection: ≥ 4/5. Trajectories rated ≤ 3 are stored but never injected.

### Component 4 — JSONL export (feeds Ablation B + reproducibility)

```python
def export_jsonl(min_rating=None, output_path=None):
    # Fetch annotated traces from Phoenix API
    # Write {question, trajectory, answer, rating, step_ratings, run_id} per line
```

Running this on B1 trajectory traces after rating them produces `ablations/B_process_rewards/trajectory_labels.jsonl` — the exact file TASK-029 specifies. The export is also committed periodically for reproducibility.

### Component 5 — DSPy (deferred until ≥50 rated examples)

Once enough rated examples accumulate, DSPy's `BootstrapFewShot` can compile an optimized static prompt from the labeled dataset. This is a batch step run offline — it does not replace the runtime few-shot retrieval in Component 3, it augments it with a curated static component.

Add when the project reaches this maturity. For now, the runtime retrieval in Component 3 is sufficient.

---

## What "RL" means here

| Term | This project |
|------|-------------|
| Policy | Agent's prompt (system prompt + injected few-shot examples) |
| Reward signal | User rating 1–5 on trajectory + answer, stored in Phoenix |
| Policy update | At next similar query: re-retrieve high-rated examples from Phoenix, inject into prompt |
| No model training | LLM weights never change |
| Online | Each new rated interaction immediately available for future queries |

This is in-context RL: human preference signal → updated few-shot selection → better behavior on similar queries. Sometimes called retrieval-augmented few-shot learning. The data format supports upgrading to a reward model later (per-step labels via `step_ratings`) without schema changes.

---

## Summary: what is actually custom code

| Component | Dependencies | Lines of code |
|-----------|-------------|---------------|
| Phoenix annotation posting | `arize-phoenix` (already in pyproject.toml) | ~30 |
| Query cache FAISS index | `faiss-cpu`, `sentence-transformers` (already deps) | ~60 |
| CLI rating prompt | stdlib only | ~40 |
| Runtime few-shot injection | Phoenix SDK + existing embedding model | ~50 |
| JSONL export from Phoenix | Phoenix SDK | ~20 |
| **Total** | **No new dependencies** | **~200 lines** |

---

## New tasks (revised)

| Task ID | Title | Phase | Depends on | Effort |
|---------|-------|-------|------------|--------|
| TASK-027.5 | Query cache — FAISS index over past queries + sidecar JSON | 4B | TASK-020, TASK-016 | 2h |
| TASK-027.6 | Semantic cache CLI — similarity lookup, user confirmation flow | 4B | TASK-027.5 | 1h |
| TASK-027.7 | Runtime few-shot injection from Phoenix-rated trajectories | 4B | TASK-027.5, TASK-027 | 2h |
| TASK-027.8 | CLI rating UI + Phoenix annotation posting | 4B | TASK-027 | 1h |
| TASK-027.9 | JSONL export from Phoenix (feeds TASK-029 + reproducibility) | 4B | TASK-027.8 | 1h |

TASK-029 (SME trajectory labeling) is simplified: use the rating UI (TASK-027.8) on B1 runs; `export_jsonl()` (TASK-027.9) produces the required file.

DSPy integration: add as TASK-027.10 only after ≥50 rated examples exist.

---

## Open questions (unchanged from initial exploration)

1. **Rating granularity**: mandatory full-answer (1–5) + optional per-step (good/suboptimal/wrong)? Per-step directly feeds Ablation B but adds friction.

2. **Similarity threshold**: 0.88 default, configurable in YAML — does that feel right?

3. **Benchmark isolation**: `cache: false` in all benchmark YAML configs so eval scores are always from fresh retrieval. Any exceptions?

---

## Revision note

Initial design proposed a custom SQLite feedback store (`feedback.py` with full schema). Dropped after library research showed Phoenix already does this via its annotation API. The only custom components are the query-cache FAISS index (no existing library covers this without GPTCache, which is abandoned) and the runtime retrieval + injection logic (DSPy does not do this at runtime). No new dependencies added by any of the new tasks.
