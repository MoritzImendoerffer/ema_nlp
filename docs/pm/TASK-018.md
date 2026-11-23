---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-018
status: done
kind: mechanism
title: "Take each item's trace id from the adapter's own root span"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-018 — Take each item's trace id from the adapter's own root span

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The newest-trace-of-the-process lookup (mlflow.get_last_active_trace_id) gave nothing for T1 because the trace was written late. The adapter knows its own root span; its id does not depend on when the exporter writes the trace. The fallback to trace_id_fn stays for a failed item and for a runnable without the key.

## Acceptance criteria

- [x] `tests/test_eval_predict.py::test_predict_items_prefers_the_trace_id_the_agent_returns` passes: an ainvoke result with trace_id gives that id even when the trace-id function returns nothing new
- [x] `tests/test_eval_runner.py::test_adapter_returns_its_own_trace_id` passes: AgentWorkflowAdapter.ainvoke returns the id of the trace that holds its root span
- [x] `make test` passes and `make lint` passes, each run on its own line

## What was built

harness/agents/workflow_adapter.py: ainvoke returns trace_id, the id of the trace of its own root span (None when tracing is off); app.py reads only named keys, so the extra key changes nothing there. harness/eval/predict.py: apredict_items uses that id first and falls back to trace_id_fn (failed item, runnable without the key). 2 new tests (predict prefers the returned id when trace_id_fn gives nothing; the adapter's id is the trace whose root span is AgentWorkflowAdapter.invoke). make test: 736 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/agents/workflow_adapter.py`
- `harness/eval/predict.py`
- `tests/test_eval_predict.py`
- `tests/test_eval_runner.py`
