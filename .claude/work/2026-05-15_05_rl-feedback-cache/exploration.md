# Exploration: RL feedback, semantic cache, and online learning

**Date:** 2026-05-15  
**Phase context:** Phase 1 in progress. LlamaIndex + Phoenix decided. TASK-027 (ReActAgent) and TASK-029 (trajectory labeling) are not yet built — good timing to design this now so the data model is right from the start.

---

## What the user is asking for

Three connected features:

1. **Trajectory rating** — after a query, the user can rate how well the agent did (the reasoning chain, not just the answer). These ratings become a feedback signal.

2. **Online learning from ratings** — the agent uses past high-rated trajectories on similar questions as few-shot context, so it doesn't rediscover a good strategy for question types it has already handled well.

3. **Semantic query cache with user confirmation** — before running the full pipeline, show the user the top-k most similar past questions (with their cached answers and ratings). The user chooses: use cached answer, use cached answer as a starting point, or trigger a fresh full retrieval.

---

## Relationship to existing roadmap

This request overlaps significantly with Ablation B but extends it in an important direction:

| | Ablation B (existing) | This new feature |
|---|---|---|
| Who labels? | SME, batch, before the experiment | User, online, during actual use |
| What is labeled? | Individual trajectory steps (good/suboptimal/wrong) | Full trajectory + final answer (rating scale) |
| When is it used? | As few-shot examples in agent prompt (static set) | At query time, retrieved dynamically for similar questions |
| Learning mechanism | Prompt injection (few-shot) | Same, but the example pool grows with use |
| Cache | No | Yes — semantic similarity over past queries |

The right approach: **design the data model once, use it for both Ablation B and the online system**. Ablation B's `trajectory_labels.jsonl` becomes a seed for the online store; the online store grows as users interact.

---

## Architecture

### Component 1 — Feedback store

A persistent store of `(query, trajectory, answer, rating)` tuples. Nothing exotic — SQLite is the right choice:

- Lightweight, zero-config, single file
- Easily queryable for statistics
- Portable (committed or left in `~/.local/share/ema_nlp/` on each machine)
- Can export to JSONL for reproducibility

Schema:
```sql
CREATE TABLE interactions (
    id           TEXT PRIMARY KEY,   -- hash(query + timestamp)
    query        TEXT NOT NULL,
    query_vec    BLOB,               -- stored embedding for fast similarity search
    trajectory   JSON,              -- list of {thought, action, observation} steps
    answer       TEXT,
    cited_qa_ids JSON,              -- list of qa_ids the agent cited
    rating       INTEGER,           -- 1–5 (NULL = not yet rated)
    rating_note  TEXT,              -- optional free-text from user
    step_ratings JSON,              -- optional per-step labels (good/suboptimal/wrong)
    run_id       TEXT,              -- links to results/<run_id>/ for the full Phoenix trace
    created_at   TEXT,
    retriever    TEXT,              -- which retriever config was used
    model        TEXT               -- which LLM was used
);
```

Why SQLite over JSONL: JSONL works for sequential writes but is awkward to query for "find top-5 most similar past queries with rating ≥ 4". SQLite makes that a one-liner.

`harness/feedback.py` — the module owning this store. Exposes:
```python
def save_interaction(query, trajectory, answer, cited_qa_ids, run_id, ...) -> str  # returns id
def rate_interaction(interaction_id, rating, note=None, step_ratings=None)
def get_similar(query_vec, k=5, min_rating=None) -> list[Interaction]
def export_jsonl(path)  # for reproducibility and Ablation B seeding
```

### Component 2 — Semantic cache

Not a true cache (which would return a stored answer silently) — instead, a **query similarity lookup** that presents matches to the user before doing anything.

Flow:
```
User submits query
    ↓
Embed query (same BGE-large model used for document retrieval)
    ↓
Search interaction store for top-k similar past queries (cosine sim > threshold)
    ↓
If any matches found:
    Show user: "These similar past questions were found:"
      [1] (sim=0.94, rating=4/5) "What is the AI limit for chronic-use products?"
           Answer: "The AI for chronic-use products is 26.5 ng/day..."
           Trajectory: 3 steps, followed cross-ref chain via Q22→Q10
      [2] (sim=0.87, rating=5/5) "What thresholds apply during CAPA for nitrosamines?"
           Answer: "During CAPA implementation, interim limits of..."
           Trajectory: 4 steps
    Options:
      [a] Use cached answer from [1]
      [b] Use cached answer from [2]
      [c] Use [1] as starting context but run fresh retrieval
      [d] Ignore cache, run full pipeline
    ↓
User chooses
    ↓
If a or b: return stored answer + show stored trajectory (no new retrieval)
If c: inject cached trajectory as few-shot context, run fresh agent
If d: run full pipeline, no cache influence
```

The key design choice is that **the user always sees what they're getting and why**. No silent cache hits. This directly supports the educational/transparency goal.

The similarity threshold (default 0.90) should be configurable. Retrieval-only queries (no agent) skip the cache lookup since those don't have trajectories to show.

### Component 3 — Few-shot injection from rated trajectories

When the agent runs (cases c and d from above), it retrieves the top-k highest-rated past trajectories for similar questions and injects them into the agent's planning prompt as few-shot examples:

```
[System prompt — existing]

[Few-shot context — injected]
Past similar questions handled well:

Q: "What is the AI limit for chronic-use products?" (similarity: 0.94, rating: 4/5)
Reasoning chain:
  Step 1: search("AI limit chronic-use nitrosamine") → [Q22, Q10]
  Step 2: follow_cross_refs("nitrosamines:Q22") → Q10 contains the numeric threshold
  Step 3: answer(text="The AI for chronic-use...", cited_ids=["nitrosamines:Q10"])
---

[Current query — existing]
Q: "..."
```

This is standard few-shot prompting, not model training. No weights are updated. The "learning" is purely in-context. This is important for:
- Reproducibility: every prompt can be reconstructed from the feedback store
- Transparency: the injected examples are visible in the Phoenix trace
- Safety: a bad rating prevents the trajectory from being used as an example (min_rating filter)

Rating threshold for injection: ≥ 4/5. Below that, trajectories are stored but not injected.

### Component 4 — Rating UI

Two modes:

**Minimal (CLI, v1):**
```
Query: "What AI limit applies during CAPA for chronic-use nitrosamines?"

Answer: The AI for chronic-use products during CAPA implementation...

Trajectory:
  Step 1: search("CAPA limit chronic nitrosamine") → Q22, Q10, Q8
  Step 2: follow_cross_refs("nitrosamines:Q22") → Q10 (AI = 26.5 ng/day)
  Step 3: answer(cited=["nitrosamines:Q10", "nitrosamines:Q8"])

Rate this answer (1=poor, 5=excellent, Enter to skip): 4
Note (optional): Good chain traversal, answer complete
Rate individual steps? [y/N]: y
  Step 1 [good/suboptimal/wrong]: good
  Step 2 [good/suboptimal/wrong]: good
  Step 3 [good/suboptimal/wrong]: good
```

**Web UI (v1.5, Gradio or Streamlit):**
A minimal page that shows the query, answer, trajectory (collapsed/expandable), and a rating widget. The Phoenix trace viewer already shows the trace — the rating UI just adds a star rating and save button on top.

Gradio is the right choice: it's already popular in ML projects, zero-config, can be launched from `run_eval.py` alongside Phoenix.

---

## Relationship to Ablation B in detail

Ablation B (TASK-029) requires labeling ~50 trajectory steps as good/suboptimal/wrong. With the feedback store designed above:

- **The online rating system IS the labeling tool** for Ablation B — the user rates trajectories from B1 runs using the same interface
- `export_jsonl()` on the feedback store produces `trajectory_labels.jsonl` — the exact file TASK-029 specifies
- This eliminates the need to build a separate labeling workflow for TASK-029

This is a significant simplification. Instead of a batch labeling task, TASK-029 becomes "run 5 questions from B1, rate them in the feedback UI."

---

## What "RL" means here (and what it doesn't)

The user uses "reinforcement learning" loosely, which is correct in spirit. More precisely:

| Term | What happens in this project |
|------|------------------------------|
| Policy | The agent's prompt (including few-shot examples) |
| Reward signal | User rating (1–5) on trajectory + answer |
| Policy update | Re-retrieval of high-rated few-shot examples from feedback store; included in next similar query's prompt |
| No model training | Weights of the LLM never change — all learning is in the prompt context |
| Online vs batch | Online (each new rated interaction is immediately available for future similar queries) |

This is sometimes called **prompt-based reinforcement** or **retrieval-augmented few-shot learning**. It's also related to RLHF in spirit (human preference signal → better behavior) but without the actual RL training loop.

For v2, if the project grows, the feedback store could seed a reward model (TASK-029's trajectory labels as training data) or be used for actual fine-tuning of a smaller open model. The data schema is designed to support that — `step_ratings` captures per-step labels that would be needed for process-reward model training.

---

## Fit with the project's educational goal

The semantic cache with user confirmation is particularly well-aligned with the learning/exploration goal:

- The user sees *why* a question is considered similar (similarity score, side-by-side question display)
- They see the cached trajectory before deciding to use it — they can learn from it
- Choosing "use as starting context" (option c) is itself an educational act: "the system thinks this is similar, let me see if a fresh retrieval changes anything"
- Rating trajectories teaches users what good vs. bad retrieval strategies look like

This turns every query into a potential learning moment, not just for the agent but for the user.

---

## Implementation scope: v1 vs defer

| Feature | Complexity | Recommendation |
|---------|-----------|----------------|
| Feedback store (SQLite) | Low | v1 — build alongside TASK-027 (agent) |
| `get_similar()` with cosine search | Low | v1 — reuses existing embedding model |
| CLI rating UI | Low | v1 — 30 lines of code, no new deps |
| Cache presentation (show similar questions) | Low | v1 — CLI list before running pipeline |
| Few-shot injection from rated trajectories | Low-medium | v1 — prompt construction, no new deps |
| Export to trajectory_labels.jsonl (feeds Ablation B) | Low | v1 — eliminates separate TASK-029 labeling tool |
| Gradio rating UI | Medium | v1.5 — after CLI version works |
| Per-step rating in UI | Low addition | v1 alongside CLI |
| Actual reward model training | High | v2+ only |

The CLI path is ~200 lines of new code total across `feedback.py`, additions to `react_agent.py`, and `run_eval.py`. No new dependencies.

---

## New tasks to add to the plan

| Task ID | Title | Phase | Depends on | Effort |
|---------|-------|-------|------------|--------|
| TASK-027.5 | Feedback store — SQLite schema + `feedback.py` | 4B | TASK-020 | 2h |
| TASK-027.6 | Semantic query cache — similarity lookup + CLI confirmation flow | 4B | TASK-027.5 | 2h |
| TASK-027.7 | Few-shot injection from rated trajectories into agent prompt | 4B | TASK-027.5, TASK-027 | 2h |
| TASK-027.8 | CLI rating UI (answer + trajectory, per-step optional) | 4B | TASK-027.5 | 1h |

TASK-029 (SME trajectory labeling) is simplified: instead of a separate labeling workflow, use the rating UI on B1 trajectories. The `export_jsonl()` method produces the required file.

---

## Open questions before building

1. **Rating granularity**: full answer only (1–5 stars) is simplest. Per-step (good/suboptimal/wrong) is more useful for Ablation B but more work for the user. Recommendation: full-answer rating mandatory, per-step optional.

2. **Similarity threshold for cache display**: 0.90 cosine is tight; 0.80 will show more suggestions but with more false positives. Should be configurable in the YAML config.

3. **Where does the feedback store live?** Two options:
   - In the repo at `harness/feedback.db` — sharable, reproducible, but grows with use and shouldn't be committed if it contains sensitive queries
   - At `~/.local/share/ema_nlp/feedback.db` — local, never committed, each machine has its own history
   - Recommendation: default to `~/.local/share/ema_nlp/feedback.db` (machine-local); add an export command to dump it for reproducibility; the exported JSONL can be committed

4. **Interaction with the benchmark**: the benchmark should always use fresh retrieval (no cache), since the point is to measure the system. The cache should only apply to interactive/exploratory use. The `--no-cache` flag in the config handles this.
