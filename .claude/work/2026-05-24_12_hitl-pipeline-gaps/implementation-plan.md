# Implementation plan: HITL pipeline gaps

**Work unit:** `2026-05-24_12_hitl-pipeline-gaps`  
**Source:** CLAUDE_GUIDANCE.md (Opus 4.7 analysis), user decisions 2026-05-24  
**Goal:** Make the HITL labeling loop runnable end-to-end before resuming benchmarking.

---

## Context

REFACT-001–021 are complete. The harness now has clean workflow/model abstractions. But several items block the HITL labeling loop:

- The B1 sanity script crashes (imports a missing module)
- The native ReAct workflow produces catastrophically bad answers (1.82/5) — format compliance failure
- The label_session CLI doesn't exist
- The rated few-shot injection loop doesn't close (rated examples are never consulted)
- Legacy code (`react.py`, dead `cache:` fields) adds maintenance tax

Benchmarking (REFACT-022–024) is deferred until these are resolved.

---

## Critical path

```
HITL-001 (delete react.py)  ──────────────────────────────────────┐
HITL-002 (remove cache:)    ──────────────────────────────────────┤
HITL-003 (fix import)       ──────────────────────────────────────┤─→ HITL-005 (re-run sanity) ─→ done
HITL-004a (Opus diagnostic) → HITL-004b (fix react) ──────────────┘
                                    │
                                    └──→ HITL-006 (label_session) → HITL-007 (fewshot wiring)
```

HITL-001, 002, 003, 004a can all start in parallel (no dependencies between them).

---

## Tasks

### HITL-001 — Delete legacy react.py (~0.5 hr)

**Files:** `harness/workflows/react.py` (delete), `harness/workflows/registry.py`, `docs/ARCHITECTURE.md`, `docs/RETRIEVAL_PIPELINE.md`

Delete the FunctionAgent-based react.py and remove the `react_legacy` entry from `WORKFLOW_REGISTRY`. Update ARCHITECTURE.md (line 314 references `_ReactRunner` in `react.py`) and RETRIEVAL_PIPELINE.md (line 336 says both implementations "Used") to describe only the native ReAct.

Verify: `grep -r "from harness.workflows.react import"` returns nothing; `pytest tests/` passes.

---

### HITL-002 — Remove dead `cache:` field (~0.25 hr)

**Files:** `harness/configs/*.yaml` (20 files), `harness/run_eval.py`

Remove `cache: false` from all 20 YAML configs. Remove the dead `if cfg.get("cache") ... log.warning(...)` block from `run_eval.py` (currently lines 71-73).

---

### HITL-003 — Fix broken import in run_b1_sanity.py (~1 hr)

**Files:** `ablations/B_process_rewards/run_b1_sanity.py`, `harness/agents/__init__.py`

Replace the `ReActRAGAgent` construction with `get_workflow("react", index=index, llm=get_llm("agent"))`. Update `_run_questions()` to call `workflow.invoke({"question": q})` and extract `result["answer_text"]` and `result.get("trajectory", [])`.

Delete `harness/agents/__init__.py` (the directory only has this empty file — the directory served no purpose without `react_agent.py`).

Verify: `python -m ablations.B_process_rewards.run_b1_sanity --dry-run` exits without ImportError.

**Important:** Do NOT re-run the full sanity yet. That's HITL-005, after react is fixed.

---

### HITL-004a — Diagnose react workflow failure with Opus (~1.5 hr including LLM run)

**Files:** `harness/configs/models.yaml` (temporary edit), `harness/configs/workflow_react.yaml`

Temporarily change `models.yaml roles.agent` from `claude_haiku` to `claude_opus`. Run `workflow_react.yaml` on 8 benchmark questions (bench_ids: T1-001, T1-002, T2-001, T2-002, T3-001, T3-002, T4-001, T4-002) — add a `benchmark.ids:` filter to the config or pass them explicitly.

Inspect the generated answers:
- Do they contain `Final Answer:` with substantive content?
- Do any still show "I was unable to retrieve..."?
- How many tool calls appear in the trajectory?

Write findings to `react_diagnosis.md` in this work unit directory. Report conclusion before any further code change.

---

### HITL-004b — Fix react workflow based on diagnosis (~1.5 hr)

**Files:** `harness/configs/models.yaml` and/or `harness/workflows/react_native.py`

Two paths depending on 004a findings:

**If Opus recovers scores (H1 confirmed):** Set `models.yaml roles.agent: claude_opus` permanently (or `claude_sonnet` as cost compromise). Document the decision in `DECISIONS.md`. Re-run 8-question sample to confirm.

**If Opus also fails (prompt issue, H2/H3):** Redesign `_SYSTEM_PROMPT` in `react_native.py` — tighter format instructions, add a worked example, reduce `MAX_ITERATIONS` to 3 to fail faster. Possibly also increase `tool_result[:800]` truncation limit. Re-test with Haiku.

Acceptance: all 8 sample questions produce a substantive `Final Answer:` response (no truncation, no refusal pattern).

---

### HITL-005 — Re-run b1_sanity and confirm trajectories (~0.5 hr)

**Files:** `ablations/B_process_rewards/b1_trajectories.jsonl`

After HITL-003 (script fixed) and HITL-004b (react fixed): run `python -m ablations.B_process_rewards.run_b1_sanity`. Verify all 5 rows in `b1_trajectories.jsonl` have `trajectory len > 0` and non-empty answers.

---

### HITL-006 — Build harness/label_session.py (~3 hr)

**Files:** `harness/label_session.py` (new)

CLI script. Interface:

```bash
python -m harness.label_session \
    --workflow crag \
    --config harness/configs/workflow_crag.yaml \
    --n 20 \
    --sample stratified \
    [--session-id SESSION_ID]   # auto-generated UUID if omitted
```

Key design:

1. **Sampling:** `--sample stratified` draws ceil(n/4) from each type; `--sample uniform` draws n randomly. If a type has fewer questions than needed, sample with replacement.
2. **Checkpoint:** write `~/Nextcloud/Datasets/ema_nlp/label_sessions/{session_id}.jsonl` incrementally (one row per rated question). On startup, read checkpoint and skip already-rated bench_ids.
3. **Per question:** run workflow, display answer + cited qa_ids, call `prompt_for_rating(run_id, question, answer_text, trajectory, cache=cache)` from `harness/rating.py`.
4. **Rating=None** (user skips) is recorded as `"rating": null` in the checkpoint — not as 0.
5. **End summary:** print table of rated/skipped by type, avg rating, total trajectory steps collected.

Checkpoint row schema:
```json
{
  "bench_id": "T1-001", "type": "T1", "question": "...", "answer_text": "...",
  "cited_qa_ids": [], "rating": 4, "run_id": "uuid", "workflow": "crag",
  "timestamp": "2026-05-24T..."
}
```

Note: `--workflow` accepts any key from `WORKFLOW_REGISTRY`. The script is not react-specific.

---

### HITL-007 — Wire get_fewshot_context() as shared adapter (~2 hr)

**Files:** `app.py`, `harness/run_eval.py`, `harness/configs/*.yaml`

**app.py changes:**
- Obtain `query_vec` by calling the embed model on the question (already available from cache lookup path).
- Replace the `few_shot_block = CacheEntry.answer_summary` logic (lines 186-191) with `get_fewshot_context(query_vec, cache, k=3, min_rating=4)`.
- Result is `None` → empty string (same fail-closed behaviour as before, but now rating-gated).

**run_eval.py changes:**
- Read `cfg.get("cache_inject", False)` from config.
- When `True`: after building the index and before the eval loop, construct a `QueryCache` instance; inside the per-item loop, embed the question, call `get_fewshot_context()`, pass result as `few_shot_context` to `workflow.invoke()`.
- When `False` (default): `few_shot_context = ""` as today.

**YAML configs:**
- Add `cache_inject: false` to all eval YAML configs (parallel to the `cache:` field removal in HITL-002).

**Behaviour change note:** The current `app.py` injects from any cache entry above similarity threshold, regardless of rating. After this change, injection only happens when ≥ 3 entries with rating ≥ 4 exist. Injection frequency will be lower until the labeling loop (HITL-006) produces enough rated examples. This is correct behaviour — junk examples hurt more than they help.

---

## Quality assurance

After all tasks:
- `pytest tests/` passes
- `python -m harness.label_session --dry-run` (once implemented) works
- `python -m ablations.B_process_rewards.run_b1_sanity --dry-run` works
- `grep -r "react_agent\|react_legacy\|ReActRAGAgent\|cache: false" harness/ ablations/` returns nothing
- `grep -r "from harness.workflows.react import" .` returns nothing
