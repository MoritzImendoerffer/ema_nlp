---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-009
status: done
kind: contract
title: "Bind the judge role to a new models.yaml entry for claude-opus-5-5, and stop sending temperature to that model"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-009 — Bind the judge role to a new models.yaml entry for claude-opus-5-5, and stop sending temperature to that model

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

What changes. `harness/configs/models.yaml` gets one entry for the model id `claude-opus-5-5` (provider `anthropic`), and `roles.judge` (line 55) names it. All ten recipes generate with `claude_opus`, which is `claude-opus-4-7` (lines 26-31). After this task the default judge is a model that no recipe generates with. This is decision E of the proposal.

The condition of decision E is met. On 2026-11-23 `GET /v1/models` on the configured endpoint listed `claude-opus-5-5` among 15 ids, and two real judge calls through `build_judge` with `anthropic:/claude-opus-5-5` returned a value (`exploration.md` section 8.1). If this task runs on a later day, ask the endpoint again; the call costs nothing. Write no model id from memory.

The second reader of `roles.judge`, which the proposal does not name. `harness/judge.py:71` builds its model with `harness.llms.get_llm(model_role)`, and that path sends `temperature: 0.0`. One real call with `claude-opus-5-5` on that path returned `400 invalid_request_error: temperature is deprecated for this model` (`exploration.md` section 8.2). `_NO_TEMPERATURE_PREFIXES` (`harness/llms.py:118`) holds `claude-sonnet-5`, `claude-fable-5` and `claude-mythos-5`, and not `claude-opus-5`. `run_inline_judges` swallows a judge error and logs a warning (`harness/eval/inline_judge.py:104-105`). Without the prefix, the recipe `agentic_judged` loses its inline judge on every turn with no visible sign. So the prefix and the binding land in one task. The real call in the acceptance list is the proof; a unit test proves only the wrapper.

The entry keeps a `temperature` field: the loader reads it without a default (`float(d['temperature'])` in `harness/llms.py`), and the wrapper strips it before the request.

Plan decision: the entry's key is `claude_opus_5_5`. `tests/test_models.py::test_models_yaml_has_all_models` checks a subset of names and needs no change.

What happens to what was written before. The 17 runs and the 85 judge values per judge in `mlflow.db` were judged by the model bound to `roles.judge` at the time, and carry no judge tag. They stay as they are. A number from the new judge starts a new series: two numbers compare only when the same judge produced them (`DECISIONS.md`, 'The judge model is a setting'). No number is repeated now (decision D).

Why after TASK-007: from the first run with the new judge, the run records which model judged it.

The same family. The generator and the judge are both Claude models. Every `docs/eval/` page that reports a judged number has to say so (decision B).

## Acceptance criteria

- [x] `.venv/bin/python -c "from harness.models import load_model_for_role as f; print(f('judge').model_id)"` prints `claude-opus-5-5`
- [x] `tests/test_llms.py::test_opus_5_5_drops_temperature` exists and passes: the wrapper built for the model id `claude-opus-5-5` has no `temperature` in its `_model_kwargs`
- [x] `tests/test_models.py::test_no_recipe_generates_with_the_judge_model` exists and passes: for each of the 10 files in `harness/configs/recipes/`, the model id of the recipe's model differs from the model id of `roles.judge`
- [x] `tests/test_models.py::test_judge_role_is_opus` passes unchanged
- [x] One real call, which costs one short completion: `.venv/bin/python -c "import config; from harness.judge import Judge; print(Judge().faithfulness('What is 2 + 2?', '4', ['2 + 2 is 4.']))"` prints a result whose `score` is between 1 and 5, and the output holds no line with the word `deprecated`
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-007]]

## What was built

harness/configs/models.yaml: new entry claude_opus_5_5 (provider anthropic, model_id claude-opus-5-5, max_tokens 4096, temperature 0.0 kept for the loader), roles.judge -> claude_opus_5_5; the claude_opus description no longer claims the judge role. harness/llms.py: 'claude-opus-5' added to _NO_TEMPERATURE_PREFIXES. load_model_for_role('judge').model_id prints claude-opus-5-5. New tests: test_opus_5_5_drops_temperature; test_no_recipe_generates_with_the_judge_model (all 10 recipes generate with a model id other than the judge's). test_judge_role_is_opus passes unchanged. The endpoint was not asked again: same day as exploration section 8.1 (2026-11-23). One real call, one short completion, through harness/judge.py: Judge().faithfulness('What is 2 + 2?', '4', ['2 + 2 is 4.']) returned {'score': 5, ...}, exit 0, 0 lines with 'deprecated'. Earlier runs in mlflow.db stay as they are, judged by claude-opus-4-7 and untagged; a number from the new judge starts a new series. Generator and judge are both Claude models. make test: 715 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/configs/models.yaml`
- `harness/llms.py`
- `tests/test_llms.py`
- `tests/test_models.py`
