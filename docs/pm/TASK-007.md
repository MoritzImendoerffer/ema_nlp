---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-007
status: done
kind: wiring
title: "Add `--judge` to scripts/run_eval.py and record the generator's and the judge's model id on every run"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-007 — Add `--judge` to scripts/run_eval.py and record the generator's and the judge's model id on every run

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The defect. `scripts/run_eval.py` has `--model` for the generator (line 25) and nothing for the judge. `run_recipe_benchmark` already takes `judge_role` (`harness/eval/runner.py:159`) and the script does not pass it (lines 31-38). A run carries three tags and neither model (`runner.py:192-199`); the store holds exactly the run tag keys `ema.recipe`, `ema.benchmark` and `ema.question_type`. `roles.judge` and all ten recipes name `claude_opus`, so every stored number was judged by the model that generated it.

What to build. `--judge <model key>` overrides `roles.judge` for one run, as `--model` overrides the recipe's model: both take a key of the `models:` section of `harness/configs/models.yaml`. The two run tags hold model ids, resolved from the keys with the loader of TASK-006. Set them when the run opens, with the three tags of TASK-005. The summary starts with one line that names both ids, and adds the warning line when they are equal.

Why ids and not keys: a key such as `claude_opus` can be rebound to another model in `models.yaml`. A number must say which model produced it (`DECISIONS.md`, 'The judge model is a setting, recorded on every run').

Keep a way to test without Neo4j. Resolving the generator's id, the judge's id and the judge's mlflow name from the recipe and the options is a pure step. Put it in a function of its own and test that.

## Acceptance criteria

- [x] `.venv/bin/python scripts/run_eval.py --help` prints a line that contains `--judge`
- [x] `tests/test_eval_runner.py::test_judge_option_reaches_the_judges` exists and passes: with the arguments `--recipe naive_rag --judge claude_sonnet` the script calls `run_recipe_benchmark` with that model key, and the judges are built with the model `anthropic:/claude-sonnet-5`
- [x] `tests/test_eval_runner.py::test_run_is_tagged_with_both_model_ids` exists and passes: the run opened by the offline driver holds `ema.generator_model` and `ema.judge_model`, and both values are model ids such as `claude-opus-4-7`, not keys such as `claude_opus`
- [x] `tests/test_eval_runner.py::test_summary_names_both_models_and_warns_when_they_are_one` exists and passes: the summary prints both ids; it holds exactly one line that starts with `WARNING` when the two ids are equal, and none when they differ
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]], [[TASK-006]]

## What was built

scripts/run_eval.py: --judge <models.yaml key> passed to run_recipe_benchmark(judge=). harness/eval/runner.py: ModelChoice (generator and judge model ids, the judge route; run_tags() gives ema.generator_model + ema.judge_model; header() names both ids and adds one WARNING line when they are equal), resolve_models(recipe_model, model=, judge=, judge_role=) as the pure step, and EvalReport(summaries, header) with text(); run_recipe_benchmark returns an EvalReport and opens each run with the two model tags beside the three of TASK-005. 3 new tests: --judge claude_sonnet reaches run_recipe_benchmark and its route builds both judges with anthropic:/claude-sonnet-5; a run from the offline driver holds claude-opus-4-7 and claude-sonnet-5 as tags; the header has one WARNING line when the ids are equal and none when they differ. run_eval.py --help lists --judge. make test: 711 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `scripts/run_eval.py`
- `harness/eval/runner.py`
- `tests/test_eval_runner.py`
