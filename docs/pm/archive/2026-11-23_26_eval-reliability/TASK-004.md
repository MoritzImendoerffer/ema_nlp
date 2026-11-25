---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-004
status: done
kind: mechanism
title: "Add the pure functions for the judged rows, the counts and the printed summary"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-004 — Add the pure functions for the judged rows, the counts and the printed summary

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The defects, each in `harness/eval/runner.py` today.
- `to_eval_data` (lines 62-74) keeps the question and the gold answer and drops `bench_id`, so a trace cannot be matched to its item. Both benchmark files carry a unique `bench_id` (45 and 5 rows).
- `mean_scores` (lines 90-101) skips a value that `float()` rejects and counts nothing. Run `5ba51e5c` (`topic_agent`, T1, 20 traces) stores `correctness_mean` 4.353, which is 74 / 17: three rows are missing from it and nothing says so.
- `summarize` (lines 204-213) prints one mean per judge and no count.

What to build, as three functions with new names so that the old ones keep working until TASK-005.
1. The rows for `mlflow.genai.evaluate`: one dict per finished item with `inputs`, `outputs`, `expectations`, `tags` and, when given, `trace`. A failed item gives no row. mlflow 3.14.0 accepts these five keys together (`mlflow/genai/evaluation/entities.py:125-174`); with `trace` present the judge values land on the agent's own trace (`exploration.md` section 5.1, checked with a run).
2. The counts per judge: the mean over the numeric values, n as the number of numeric values, and invalid as finished rows minus n. Defining invalid by subtraction also counts a judge call that left no assessment at all.
3. The summary text. One line per question type with `n=`, `failed=`, `judge_invalid=` (the sum over the judges), then each mean followed by its own n in brackets, and its own invalid count when that is above 0. Under it one line per failed item: the id and the first 200 characters of the error. A type with no finished row prints no mean.

Decision A of the proposal fixes the rule: a failed item is listed and left out of every mean (`DECISIONS.md`, 'A failed run is listed and left out of the mean').

Plan decision, not in the proposal: each mean carries its own n. The proposal lists the counts `n`, `failed` and `judge_invalid`. With two judges, one total `judge_invalid` does not say how many rows stand behind each mean, and the backlog row asks that every mean prints its n.

No caller yet: TASK-005.

## Acceptance criteria

- [x] `tests/test_eval_runner.py::test_eval_rows_carry_bench_id_and_leave_out_a_failed_item` exists and passes: from three items of which the second failed, the function returns two rows; each row has `inputs.question`, `outputs`, `expectations.gold_answer` and `tags['ema.bench_id']`; a row has the key `trace` only when a trace object was given for its item
- [x] `tests/test_eval_runner.py::test_score_stats_counts_a_value_that_is_not_a_number` exists and passes: the faithfulness values `5`, `" agent errored"`, `None` and `3` over 4 finished rows give mean 4.0, n 2 and invalid 2
- [x] `tests/test_eval_runner.py::test_score_stats_counts_a_missing_judge_value` exists and passes: 3 finished rows and 2 numeric values give invalid 1
- [x] `tests/test_eval_runner.py::test_format_summary_prints_n_failed_ids_and_invalid` exists and passes: for a type with 3 items of which `T1-002` failed, the text contains `n=3 failed=1`, `T1-002`, the first line of that item's error, `judge_invalid=0`, and `(n=2)` directly after each of the two means
- [x] `tests/test_eval_runner.py::test_format_summary_for_a_type_where_every_item_failed` exists and passes: the line shows `n=3 failed=3` and no mean
- [x] The 9 tests that exist today in `tests/test_eval_runner.py` pass unchanged: `to_eval_data`, `mean_scores` and `summarize` stay until TASK-005
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-002]]

## What was built

harness/eval/runner.py gains judged_rows (one row per finished item: inputs, outputs, expectations, tags['ema.bench_id'], and trace when given; a failed item gives none), JudgeStats + score_stats (mean over numeric values, n, invalid = finished - n; bools and NaN are not numeric), TypeSummary (items, stats, no_trace, run_id; n, failed, judge_invalid) and format_summary (one line per type with n=, failed=, judge_invalid=, no_trace= when > 0, each mean with its own '(n=K)' or '(n=K invalid=J)'; then one line per failed item with the id and the first 200 characters of the error's first line; no mean when nothing finished). 5 new tests; the 9 old tests pass unchanged. No caller yet: TASK-005. make test: 702 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/eval/runner.py`
- `tests/test_eval_runner.py`
