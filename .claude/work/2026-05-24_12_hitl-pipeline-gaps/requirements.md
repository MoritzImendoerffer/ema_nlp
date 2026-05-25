# Requirements: HITL pipeline gaps

Source: CLAUDE_GUIDANCE.md (Opus 4.7 analysis), user decisions 2026-05-24.

## Scope

Fix the P0 blockers and P1 cleanups identified in CLAUDE_GUIDANCE.md, in the order that makes
the HITL labeling loop actually closeable. Benchmark runs are deferred until setup is complete.

## Out of scope

- REFACT-022/023/024 (benchmark completion, comparison reports) — deferred
- P2 (Streamlit dashboard) — deferred
- P3 (lift harness wrapper, skip token) — deferred

## Decisions made

| Item | Decision |
|------|----------|
| P0.3 approach | Swap agent role to Opus temporarily to validate format-compliance hypothesis |
| P0.3 run size | 8 questions (2 per type) — sufficient for diagnosis, avoids full Opus benchmark cost |
| P0.4 v1 features | Resume on interrupt + stratified sampling; no multi-workflow comparison |
| P1.1 injection point | Shared adapter in run_eval.py + app.py (not inside workflows); replaces current app.py similarity-only logic |
| P1.1 eval protection | cache_inject: false in all eval YAML configs; true only for interactive use |
| P1.3 | Remove cache: field from all YAML configs now |

## Functional requirements

### Task group 1 — cleanup (no new behavior)
- `harness/workflows/react.py` and the `react_legacy` registry entry are deleted
- `cache: false` removed from all 20 YAML configs; dead warning removed from `run_eval.py`
- `ARCHITECTURE.md` and `RETRIEVAL_PIPELINE.md` describe only the native ReAct implementation

### Task group 2 — react diagnosis and fix
- The agent role in `models.yaml` is temporarily changed to `claude_opus` (or `claude_sonnet`)
- `workflow_react.yaml` is run on an 8-question sample; findings are documented
- Based on findings: either prompt redesign for Haiku OR `models.yaml` agent role permanently updated
- After fix: react workflow produces answers above baseline (> 3.0/5 correctness on the sample)

### Task group 3 — sanity script repair
- `run_b1_sanity.py` no longer imports the missing `react_agent.py`
- Script uses `get_workflow("react", ...)` from the registry
- After P0.3 fix: re-running sanity produces 5 non-empty trajectories

### Task group 4 — label_session CLI
- `python -m harness.label_session --workflow react --config ... --n 20 --sample stratified`
- Samples 5 questions from each of T1/T2/T3/T4
- Runs each question through the named workflow, shows answer + cited qa_ids
- Prompts for 1-5 rating via `harness/rating.py:prompt_for_rating`
- Writes checkpoint after each question; re-running resumes from last checkpoint
- Prints end-of-session summary: rated/skipped, avg rating, steps collected

### Task group 5 — fewshot injection wiring
- `get_fewshot_context()` called in `app.py` on every chat turn (replaces current similarity-only logic)
- `get_fewshot_context()` called in `run_eval.py` when `cache_inject: true` in config (default: false)
- All eval YAML configs have `cache_inject: false` added
- Injection fails closed: if < 3 entries with rating ≥ 4 exist, no injection
