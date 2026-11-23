---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-002
status: done
kind: mechanism
title: "Add a prediction loop that runs every question on one event loop and records whether the agent finished"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-002 — Add a prediction loop that runs every question on one event loop and records whether the agent finished

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The defect. `AgentWorkflowAdapter.invoke` (`harness/agents/workflow_adapter.py:124-126`) calls `asyncio.run` once per question. The agent's LLM holds one `anthropic.AsyncAnthropic`, whose connection pool keeps connections that belong to the loop of an earlier question. Five evaluation traces of 2026-07-13 ended with `RuntimeError: Event loop is closed` (stack trace in `exploration.md` section 6.1). A probe without a model call reproduced it: one `asyncio.run` per call failed 3 times in 6 sequential calls; one loop for all calls failed 0 times in 40 (`exploration.md` section 6.2). So one worker alone does not end the crash. One loop for all questions does.

What to build. A result record per item (`bench_id`, question type, `ok`, `error`, `outputs`, `trace_id`), an async function that walks the benchmark rows one after the other and awaits `runnable.ainvoke({'question': ..., 'source': 'eval'})` for each inside `try`/`except Exception`, and one sync entry point that wraps the whole walk in a single `asyncio.run`. `outputs` is the dict `_prediction` builds today (`harness/eval/predict.py:33-40`), so the judges read the same keys as before.

Rules a later session would get wrong.
- Call `ainvoke`, never `invoke`. `invoke` is the one-loop-per-call path.
- Catch `Exception`, not `BaseException`. Ctrl-C and task cancellation must stop the run.
- The trace id is read after each item through a function passed in as a parameter. The default is `harness.obs.last_trace_id` (`harness/obs/tracing.py:132-140`). The parameter keeps this module and its tests free of mlflow.
- `last_trace_id` returns the newest finished trace of the process. If an item made no trace, it returns the id of the item before. Compare with the previous id and store `None` when it did not change. Otherwise two items share one trace and a judge value lands on the wrong item.
- A failed item has a trace too, with status ERROR. Keep its id; TASK-005 links it to the run.
- Keep `build_predict_fn`. `harness/eval/bootstrap.py:81-83` calls it.

No caller yet: TASK-005 wires this into `run_recipe_benchmark`. Until then `scripts/run_eval.py` behaves as it does today.

## Acceptance criteria

- [x] `tests/test_eval_predict.py::test_predict_items_counts_a_failed_item_and_goes_on` exists and passes: a stand-in whose `ainvoke` raises `RuntimeError('Event loop is closed')` on the second of three rows gives three results with `ok` equal to `[True, False, True]`; the second result's `error` starts with `RuntimeError`; each result carries its row's `bench_id`
- [x] `tests/test_eval_predict.py::test_predict_items_uses_one_event_loop` exists and passes: the stand-in records `id(asyncio.get_running_loop())` on each of three calls, and the set of ids has one element
- [x] `tests/test_eval_predict.py::test_predict_items_never_gives_two_items_one_trace_id` exists and passes: when the trace-id function returns the same id after two items in a row, the second item's `trace_id` is `None`
- [x] `tests/test_eval_predict.py::test_predict_items_carries_the_passages` exists and passes: a finished result's `outputs['context_passages']` equals the list the stand-in returned
- [x] `grep -c 'asyncio.run' harness/eval/predict.py` prints 1
- [x] The 4 tests that exist today in `tests/test_eval_predict.py` pass unchanged
- [x] `make test` passes and `make lint` passes, each run on its own line

## What was built

harness/eval/predict.py: ItemResult (bench_id, question_type, ok, error, outputs, trace_id), apredict_items (awaits runnable.ainvoke per row, catches Exception only, reads trace_id_fn before the first row and after each row and stores None when the id did not change) and predict_items (the one asyncio.run around all rows). build_predict_fn kept for bootstrap.py. Four new tests in tests/test_eval_predict.py (failed item counted, one event loop, no shared trace id, passages carried); the 4 old tests pass unchanged. grep -c asyncio.run harness/eval/predict.py = 1. No caller yet: TASK-005 wires it. make test: 697 passed, 2 skipped, 7 deselected (exit 0, run together with TASK-003). make lint: All checks passed (exit 0).

## Files it touched

- `harness/eval/predict.py`
- `tests/test_eval_predict.py`
