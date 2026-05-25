# Exploration: CLAUDE_GUIDANCE.md findings vs current state

## Verdict: assessment is accurate — 7 of 8 findings still apply

Codebase as of 2026-05-24. REFACT-001–021 complete. REFACT-022 partially complete (workflow_react results exist but crag_review has no judge scores). REFACT-023/024 pending.

---

## P0 findings — finding-by-finding

### P0.1 — Broken trajectory capture ✅ ACCURATE, HIGH PRIORITY

Evidence:
- `harness/agents/__init__.py` exists; `react_agent.py` does NOT exist in tree
- `ablations/B_process_rewards/run_b1_sanity.py` line 151 still imports `from harness.agents.react_agent import ReActRAGAgent`
- `b1_trajectories.jsonl` has 5 rows, all `trajectory len=0`, all answers empty
- The sanity script **cannot currently run**

Fix path is unambiguous: migrate `run_b1_sanity.py` to use `get_workflow("react", ...)` from the registry. The `WorkflowRunner.invoke()` result dict contains `trajectory` from `react_native.py`'s `StopEvent`.

### P0.2 — Legacy react.py still exists ✅ ACCURATE, QUICK WIN

Evidence:
- `harness/workflows/react.py` exists (FunctionAgent-based)
- `harness/workflows/registry.py` line 114: `"react_legacy": _build_react_legacy`
- `ONBOARDING.md` already acknowledges it as "targeted for removal"
- `RETRIEVAL_PIPELINE.md` line 336 still says both implementations are "Used"
- `ARCHITECTURE.md` line 314 describes `react.py` with `_ReactRunner` as live

Deletion is safe — registry isolates callers; `react_native.py` is the canonical `"react"` key.

### P0.3 — Native ReAct scores catastrophically ✅ ACCURATE, DIAGNOSIS AVAILABLE

Evidence from `results/workflow_comparison.md`:
- react native: overall correctness **1.82/5**, T3=**1.00/5**, T1=2.45/5
- Report explicitly: "truncated responses and refusals ('I was unable to retrieve...')"
- Report conclusion: "ReAct requires prompt redesign or replacement with CRAG before further evaluation"

The guidance asks to diagnose before coding. **The diagnosis already exists from REFACT-022 run.** The failure pattern matches hypothesis H1: Haiku doesn't follow the ReAct format reliably and falls through to the fallback "treat entire response as final answer" branch.

Three possible directions (need user decision):
1. **Redesign system prompt** for Haiku — tighter format constraints, shorter max_iterations
2. **Swap agent role to Opus** — expensive but would validate whether format is the issue
3. **Deprioritize react** — CRAG (3.73/5 overall) and simple_rag (4.20/5) already work; defer react fix to v2

### P0.4 — No interactive labeling script ✅ ACCURATE, NEEDS DESIGN DISCUSSION

Evidence: `find . -name "label_session*"` returns nothing. No `harness/label_session.py` exists.

Guidance says discuss design before coding. Three design questions from the assessment that need user answers:
1. Should the script resume mid-session if interrupted?
2. Should it support running multiple workflows on the same question for comparison?
3. Should it allow editing the answer text before rating?

---

## P1 findings

### P1.1 — fewshot_inject not wired up ⚠️ PARTIALLY ACCURATE

Evidence:
- `app.py` line 197: `{"question": query, "few_shot_context": few_shot_block}` — the parameter IS passed
- But `few_shot_block` at line 186-191 is built from **semantic cache hits** (`CacheEntry.answer_summary`), NOT from `get_fewshot_context()` in `harness/fewshot_inject.py`
- `harness/run_eval.py`: zero references to `fewshot_inject` or `get_fewshot_context`

The guidance's core concern holds: **the rated-trajectory few-shot path** (fetch top-k rated runs above threshold) never gets called. The cache hit path is a different thing (similarity-based one-shot from any cached entry, not filtered by rating).

The loop described in the roadmap (label → store rated trajectory → inject rated examples on similar queries) does NOT currently close.

Two design questions from the guidance (need user decision):
1. Where to inject: inside each workflow's first step (current route), or shared adapter in `run_eval.py`/`app.py`?
2. When to trigger: always, only when ≥N rated entries, or only when similarity ≥ threshold?

### P1.2 — Stale docs ✅ ACCURATE (partially addressed by REFACT-020)

Evidence:
- `ARCHITECTURE.md:314` describes `react.py` with `_ReactRunner` as live code
- `RETRIEVAL_PIPELINE.md:336` says both react implementations are "Used"
- `ONBOARDING.md:254` already notes doc references point at missing code (self-aware)

P1.2 cleanup should happen after P0.2 (delete react.py) — update docs to describe only native ReAct.

`judge.model` in YAML: `baseline_a0.yaml` has NO `judge.model` field (grep returned nothing). So this specific concern may already be resolved or was never present. `harness/judge.py` docstring confirms it uses `models.yaml` role binding directly.

### P1.3 — Dead `cache:` field in YAML configs ✅ ACCURATE, TRIVIAL

Evidence: all 20 YAML configs have `cache: false`. `run_eval.py` line 71-73 logs a warning and ignores the field. The field and the warning are dead weight.

---

## REFACT-022 completion status

The work unit state.json marks REFACT-022 as `pending`. But results exist:
- `workflow_crag`, `workflow_react`, `workflow_simple_rag` all have results  
- `workflow_crag_review` has **no judge scores** (`(no judge)` in comparison table)
- `workflow_comparison.md` exists but is incomplete for crag_review

REFACT-022's acceptance criteria require "Per-type judge metrics available for each strategy". The crag_review gap means REFACT-022 is NOT complete. Options:
1. Complete REFACT-022 by running judge on crag_review results  
2. Skip (crag_review uses a custom review step that may not produce standard judge input)

---

## Items NOT in CLAUDE_GUIDANCE.md but now observable

1. **REFACT-023 (comparison report)**: the `workflow_comparison.md` was auto-generated by `scripts/generate_comparison_report.py` and already has rich findings. REFACT-023 asks for a written narrative. The data is in — this is a documentation task.

2. **REFACT-024 (SME failure-mode breakdown)**: depends on REFACT-023. No data gap, just needs writing.

3. **REFACT-014 (SME labelling session)**: still pending — a human task. Nothing blocks it from happening except P0.3 (labelling a catastrophically broken workflow is not useful).

---

## Priority order recommendation

Given current state, suggested sequence:
1. Complete REFACT-022 (get crag_review judge scores, or accept gap and mark done)  
2. P0.2: Delete `react.py` + clean `react_legacy` from registry + update docs → immediate, no questions needed
3. P0.1: Fix `run_b1_sanity.py` → migrate to `get_workflow("react", ...)` 
4. P0.3: Decide on react fix approach (needs user decision)
5. REFACT-023: Write comparison report (data is ready)
6. P1.3: Delete `cache:` field from configs → trivial cleanup
7. REFACT-014: SME labelling (manual session, no code)
8. P1.1: Wire `get_fewshot_context()` properly (needs user design decision)
9. P0.4: Build `label_session.py` (needs user design decisions)
10. REFACT-024: Failure-mode breakdown + v2 scope
