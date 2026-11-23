---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-003
status: done
kind: mechanism
title: "Make the faithfulness and the correctness judge return an integer"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-003 — Make the faithfulness and the correctness judge return an integer

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The defect. Judge values are stored as text. Of the 85 stored values per judge in `mlflow.db`, 7 faithfulness values and 4 correctness values are not numbers; three of them are text, for example `" agent errored"` on trace `tr-97f5ef33` (`exploration.md` section 4).

The fix. `make_judge` of mlflow 3.14.0 takes `feedback_value_type` (`mlflow/genai/judges/make_judge.py:118`). `build_judge` (`harness/eval/judges.py:74-88`) already passes extra keyword arguments on. Two real judge calls on 2026-11-23 with `anthropic:/claude-opus-5-5` returned the value `5` of type `int` with `feedback_value_type=int`, and `'5'` of type `str` without it (`exploration.md` section 8.1). The present prompts work with it, so do not edit them.

What this does not end. A judge call that the provider refuses stores a null value with an error. Six of the eleven stored non-numbers are of that kind (credit balance). TASK-004 counts every such value; this task only removes the text values.

The caller exists: `run_recipe_benchmark` builds its scorers with `ema_judges` (`harness/eval/runner.py:183`).

## Acceptance criteria

- [x] `tests/test_eval_judges.py::test_ema_judges_ask_for_an_integer` exists and passes: with `mlflow.genai.judges.make_judge` replaced by a recorder, `ema_judges(model='anthropic:/x')` makes two calls and each receives `feedback_value_type` equal to `int`
- [x] `git diff --stat harness/judges/` prints nothing: the two prompt files are authored data and stay as they are
- [x] The 4 tests that exist today in `tests/test_eval_judges.py` pass unchanged
- [x] `make test` passes and `make lint` passes, each run on its own line

## What was built

ema_judges passes feedback_value_type=int to both judges through build_judge. New test test_ema_judges_ask_for_an_integer records make_judge's kwargs: 2 calls, each with int. The 4 old tests pass unchanged; git diff --stat harness/judges/ prints nothing. make test: 697 passed, 2 skipped, 7 deselected (exit 0, run together with TASK-002). make lint: All checks passed (exit 0).

## Files it touched

- `harness/eval/judges.py`
- `tests/test_eval_judges.py`
