# Open questions

Decisions not yet made. Each entry has enough context to make the decision without re-reading the full exploration. Once a question is resolved, move it to `DECISIONS.md` and remove it here.

> **Note (2026-06-04):** The feedback/caching, benchmark-construction, and agent-design questions below — rating UI granularity, benchmark `cache: false` convention, LLM judge model, T3 count, and Ablation B go/no-go — depend on the eval + LLM-judge + benchmark-runner + ablations suite, which was **archived to branch `archive/pre-llamaindex-refactor`** during the LlamaIndex retrieval refactor. They are deferred until that suite is rebuilt on the Neo4j retrieval API. Likewise, the TASK numbers referenced in these entries (TASK-016 index build, TASK-019 judge, TASK-027/028/029) predate the refactor.

---

## Feedback and caching

### Rating granularity: full-answer only, or also optional per-step?
**Context:** The CLI rating UI (TASK-027.8) will prompt for a 1–5 star rating on the full answer. Per-step labels (good / suboptimal / wrong on each agent thought-action step) would feed Ablation B's trajectory labeling directly, but add friction to every rating interaction.  
**Options:**
- Full-answer rating mandatory, per-step optional (prompted with `[y/N]`)
- Full-answer rating only; per-step done in a separate batch labeling pass over Phoenix traces
- Full-answer + per-step both mandatory (higher friction, most data)

**Recommendation:** option 1 — per-step optional. Keeps the default path fast; power users can rate steps when a trajectory is interesting.

### Similarity threshold for cache display
**Context:** The query cache (TASK-027.5) compares incoming query embedding to past queries. The threshold determines how similar a past question must be before it is shown to the user. Too high → nothing is ever shown. Too low → noisy suggestions.  
**Options:** 0.88 (tight), 0.85 (moderate), 0.80 (looser), or fully configurable in YAML with no hardcoded default.  
**Recommendation:** 0.88 default, exposed in YAML config as `cache_similarity_threshold` so it can be tuned per use case.

### Benchmark eval: hardcode `cache: false` or document as convention?
**Context:** Benchmark evaluation runs should always use fresh retrieval so scores are comparable across runs and systems. The cache is only useful for interactive/exploratory use.  
**Options:**
- Hardcode `cache: false` in all `harness/configs/baseline_*.yaml` and ablation configs
- Make `cache: true` the default and document that eval configs must set it to false
- Make `cache: false` the global default; interactive use requires explicit `cache: true`

**Recommendation:** option 3 — `cache: false` as global default, `cache: true` opt-in. Prevents accidental cache use in evals without requiring every config file to repeat the flag.

---

## Retrieval and indexing

### ~~Embedding model: confirm BGE-large-en or evaluate alternatives before Phase 3~~ — RESOLVED (2026-06-04)
**Resolution:** `BAAI/bge-large-en-v1.5` shipped. The full Neo4j `PropertyGraphIndex` was built with it (local CUDA, leaf-only — 5,817,230 leaf embeddings), so alternatives are no longer in scope without a full re-embed. See `docs/RETRIEVAL.md`; move to `DECISIONS.md` on the next sweep.

### IDMP concept list for node metadata (TASK-016.5)
**Context:** TASK-016.5 parses the IDMP RDF and extracts ~50–100 key regulatory concepts to tag Q&A nodes. The concept list needs a human review pass before it is used for filtering.  
**What needs deciding:** Which concepts are useful for retrieval filtering (vs. too fine-grained or too broad)? The script will generate `harness/ontology/concepts.yaml` for review.  
**When to decide:** After TASK-016.5 generates the candidate list. SME review takes ~30 minutes.

---

## Benchmark construction

### T3 multi-hop question count: is 43.6% chain completeness enough?
**Context:** Phase 0 found 43.6% chain completeness — 43.6% of cross-referenced Q&As are present in the corpus. The roadmap targets 10 T3 questions. T3 questions require traversing a cross-reference chain that is fully in-corpus.  
**Risk:** If most complete chains are in one topic cluster (nitrosamines), the T3 questions will lack diversity.  
**When to decide:** When TASK-008 (corpus manifest) is complete and exact chain counts are known. If complete chains are insufficient, T3 target drops from 10 to whatever the data supports.

### LLM judge model choice
**Context:** The evaluation harness (TASK-019) needs a judge model for Faithfulness and Correctness scoring. The judge should differ from the generator model to avoid self-preference bias.  
**Options:** Claude Haiku 4.5 (cheap, fast), GPT-4o-mini, a local model via Ollama.  
**When to decide:** Before TASK-019. The choice should be documented in the judge prompt file header and kept stable across all ablation runs for comparability.

---

## Agent design

### Ablation B go/no-go: will B3 (SME step labeling) happen?
**Context:** TASK-028 is a sanity check on B1 (basic ReAct agent) — 5 questions reviewed by the SME. If the agent produces incoherent trajectories, TASK-029 (step labeling) is skipped and only B4 (SME tool descriptions) runs.  
**What to watch for in B1:** coherent thought steps, no infinite loops, appropriate tool selection order, `follow_cross_refs` actually used on T3 questions.  
**When to decide:** During TASK-028. The decision is documented in `ablations/B_process_rewards/SANITY_CHECK.md`.

### Max agent steps
**Context:** The ReActAgent needs a `max_steps` limit to prevent runaway loops. Too low and it fails on T4 (synthesis); too high and it burns tokens on simple T1 questions.  
**Options:** Fixed limit (6–8 steps), adaptive per question type, or cost-based termination.  
**Recommendation:** Fixed limit of 8 steps for v1. Review after B1 sanity check.
