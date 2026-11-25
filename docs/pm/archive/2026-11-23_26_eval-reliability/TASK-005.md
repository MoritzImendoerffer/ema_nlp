---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-005
status: done
kind: wiring
title: "Switch the driver to the prediction loop: a failed item gets no judge call, and a run gets its tags when it opens"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-005 — Switch the driver to the prediction loop: a failed item gets no judge call, and a run gets its tags when it opens

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The defect. With `predict_fn`, mlflow judges a crashed row. `_run_predict` catches the exception and leaves `outputs=None`; `_run_score` then runs every scorer (mlflow 3.14.0, `mlflow/genai/evaluation/harness.py:805-822` and `840-877`). Six failed rows went to the judges in the stored runs; `tr-3a54d942` holds correctness 5 beside faithfulness 1 (`exploration.md` section 4). mlflow gives no way around this while `predict_fn` is passed. So the runner makes the predictions itself.

What to build.
1. Split the driver. `run_recipe_benchmark` keeps the part that needs Neo4j and credentials: it opens the index, builds the recipe and the judges, and calls `setup_tracing`. A second function takes any object with `ainvoke`, the benchmark rows and the scorers, and does the rest. The tests call the second function with stand-ins.
2. Predict all rows of all question types first, with the one-loop function of TASK-002. Then call `mlflow.flush_trace_async_logging()` and read each trace with `mlflow.get_trace(trace_id)`. Without the flush the trace may not be written yet; mlflow's own `predict_fn` path turns async logging off for the same reason (`harness.py:806-810`).
3. Per question type, open the run yourself: `mlflow.start_run` with the tags `ema.recipe`, `ema.benchmark` and `ema.question_type` passed at the call. `mlflow.genai.evaluate` reuses an active run (`mlflow/models/evaluation/base.py:771-784`, `_start_run_or_reuse_active_run`). Today the tags are set after `evaluate` returns (`harness/eval/runner.py:192-199`), so a run that dies has none: 7 of the 17 stored runs carry no tag.
4. Inside the run, call `run_evaluation` with the rows of TASK-004 and no `predict_fn`. Make `predict_fn` optional in `harness/eval/evaluate.py`. When a type has no finished row, skip the call: `evaluate` reads `df.iloc[0]` and fails on an empty table.
5. A failed item: link its trace to the run (`MlflowClient().link_traces_to_run`, `mlflow/tracking/client.py:1106`), tag the trace with `ema.bench_id` (`mlflow.set_trace_tag`, `mlflow/tracing/fluent.py:1576`), and write all failed items of the type to the run as the artifact `failed_rows.json` (id, error text, trace id). It gets no judge call.
6. Read the judge values back from the run's traces, as `_aggregate_run_metrics` does today (`runner.py:118-123`), and pass them to the count function of TASK-004. Log to the run: `n`, `failed`, `judge_invalid`, and per judge `<name>_mean` and `<name>_n`. Log `<name>_mean` only when at least one value is numeric.
7. `scripts/run_eval.py` prints the new summary. Delete the old functions and their three tests in this task: their last caller goes away here.

Plan decisions, not in the proposal. Each can be overruled.
- The `trace` column instead of the proposal's sketch. The sketch (`inputs`, `outputs`, `expectations` only) puts each judge value on a new trace with one span (`exploration.md` section 5.1). The proposal's fallback, `predict_fn` with one worker, is not needed.
- A finished answer without a trace is judged on a row without `trace`, and counted as `no_trace` in the summary line and as a run metric. The answer exists, so it is not a failed item.
- The failed items go to the run as an artifact. The proposal says 'logged to the run with its error' and names no form.
- The run metrics `<name>_n` and `no_trace` are beyond the three the proposal lists.

Test hygiene. The store is `sqlite:///<tmp_path>/mlflow.db`, never the repository's `mlflow.db`. The existing tests set tracing up with `setup_tracing(..., tracking_uri=f'file:{tmp_path}/mlruns', autolog=False)` (`tests/test_obs_tracing.py:20-27`); do the same and keep `autolog=False`, or LlamaIndex autolog stays switched on for every later test of the process. The offline driver function must not call `setup_tracing` itself for that reason.

What is still unproven after this task. The stand-in agent makes its trace with `mlflow.start_span`. A real trace comes from `mlflow.llama_index.autolog()` inside the runner's loop. Only the live run of TASK-015 shows that the judge values land on such a trace (`docs/PLANNING_WORKFLOW.md`, rule 10).

The command that reaches this code is `scripts/run_eval.py`. It pays for model calls, so its first real run is TASK-015. Run only `--help` here.

## Acceptance criteria

- [x] `tests/test_eval_runner.py::test_failed_item_is_counted_and_not_judged` exists and passes. It calls the real `mlflow.genai.evaluate` of the installed mlflow against a store under `tmp_path`, with a stand-in agent that raises on the second of three T1 rows and two stand-in scorers that count their calls. It asserts: the summary contains `n=3 failed=1` and the failed item's id; each scorer was called exactly 2 times; each mean is over 2 rows; the run holds the metrics `n` 3, `failed` 1 and `judge_invalid` 0; the run holds the tags `ema.recipe`, `ema.benchmark` and `ema.question_type`; the two judged traces and the failed trace each carry the tag `ema.bench_id`
- [x] `tests/test_eval_runner.py::test_judge_values_land_on_the_agents_own_trace` exists and passes: the stand-in agent opens two nested spans with `mlflow.start_span`, and the trace that holds the judge values has those spans, not a single span named `root_span`
- [x] `tests/test_eval_runner.py::test_judge_text_value_is_counted_as_invalid` exists and passes: a stand-in scorer returns `" agent errored"` for one of two rows; the summary contains `judge_invalid=1`, and the mean equals the other row's value
- [x] `tests/test_eval_runner.py::test_type_where_every_item_failed_gets_a_run_and_no_judge_call` exists and passes: the run exists with `failed` equal to `n`, and no scorer was called
- [x] `tests/test_eval_runner.py::test_finished_item_without_a_trace_is_judged_and_counted` exists and passes: the item is judged, and the summary prints `no_trace=1`
- [x] `grep -cE 'def (to_eval_data|mean_scores|summarize|_tag_eval_run|_aggregate_run_metrics)' harness/eval/runner.py` prints 0, and the three tests of the old functions (`test_to_eval_data_shape`, `test_summarize_renders_per_type_metrics`, `test_mean_scores_averages_numeric_and_skips_non_numeric`) are gone
- [x] `grep -c 'build_predict_fn' harness/eval/runner.py` prints 0, and `grep -c 'setup_tracing' harness/eval/runner.py` prints at least 1
- [x] `stat -c %y mlflow.db` prints the same time before and after `make test`: no test writes the repository's store
- [x] `.venv/bin/python scripts/run_eval.py --help` exits with status 0
- [x] `make test` passes and `make lint` passes, each run on its own line; the outcome states how many seconds the new tests add

**Depends on:** [[TASK-002]], [[TASK-003]], [[TASK-004]]

## What was built

harness/eval/runner.py: run_recipe_benchmark now builds the recipe and judges, calls setup_tracing(experiment or default_experiment()) with autolog, and hands off to evaluate_items, the offline driver: predict_items on one loop, flush_trace_async_logging, get_trace per finished item, then per question type mlflow.start_run(tags=ema.recipe/ema.benchmark/ema.question_type) -> failed items: set_trace_tag ema.bench_id + link_traces_to_run + failed_rows.json artifact, no judge call -> run_evaluation(judged_rows(... traces), configure=False) only when a row finished -> judge values read back via search_traces(run_id) -> score_stats -> metrics n, failed, judge_invalid, no_trace, <judge>_n, <judge>_mean (only when numeric). It returns a list of TypeSummary. harness/eval/evaluate.py: predict_fn optional, configure flag (False keeps the caller's tracking URI). scripts/run_eval.py prints format_summary. Deleted to_eval_data, mean_scores, _aggregate_run_metrics, _tag_eval_run, summarize and their 3 tests. 5 new tests call the real mlflow.genai.evaluate (mlflow 3.14.0) on a sqlite store under tmp: failed item counted and not judged (2 calls per scorer, metrics n 3 / failed 1 / judge_invalid 0, run tags, ema.bench_id on all 3 traces), judge values on the agent's own trace (spans agent+retrieve, no root_span), text value counted invalid, all-failed type gets a run and no judge call, finished item without trace judged and counted no_trace=1. The test fixture sets MLFLOW_ENABLE_ASYNC_TRACE_LOGGING=false: each async flush waits up to 1 s, and the file took 30 s with it; so the async flush path is proven only by TASK-015. The new tests add about 3 s (tests/test_eval_runner.py: 0.10 s -> 2.96 s, 1.4 s of it the one-time sqlite migration). mlflow.db mtime 2026-07-20 21:30:54 before and after make test. run_eval.py --help exit 0. make test: 704 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/eval/runner.py`
- `harness/eval/evaluate.py`
- `harness/eval/__init__.py`
- `scripts/run_eval.py`
- `tests/test_eval_runner.py`
