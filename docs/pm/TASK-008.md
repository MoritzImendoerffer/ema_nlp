---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-008
status: done
kind: wiring
title: "Stamp the resolved recipe on every evaluation run, and print which declared layers the runner does not run"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-008 — Stamp the resolved recipe on every evaluation run, and print which declared layers the runner does not run

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The defect. A recipe's resolved configuration reaches a trace only through `AgentWorkflowAdapter`, and only when `setup_tracing` ran. `setup_tracing` is called by `app.py:167-168` and `scripts/run_agent_demo.py:35`. Of the 100 stored evaluation traces, 90 have the root span `FunctionAgent.run` and no recipe on them; 10 carry the trace tag `ema.recipe`. TASK-005 adds the `setup_tracing` call. This task puts the configuration on the run as well.

The few-shot layer and the inline judge of a recipe run in `app.py` only (`app.py:702-715` and `740-751`). Under the runner, `regulatory_fewshot` (`fewshot.enabled: true`) and `agentic_judged` (`judge.enabled: true`) behave exactly like `regulatory_agent`, and the trace still says `ema.fewshot.enabled=True`.

What to build.
- The run tags: every `ema.*` key that `Recipe.resolved_attributes` produces (`harness/recipes/config.py:128-202`), with the effective model, temperature and k. `build_recipe` computes them and hands them to the adapter (`harness/recipes/build.py:102-105`), which keeps them in `_extra_attributes` (`harness/agents/workflow_adapter.py:48-51`). Give the adapter a read-only property and read the attributes from there. Computing them a second time in the runner would let the two copies drift.
- One summary line per declared layer that did not run. It names the layer and says that it runs in `app.py` only.

A tag value is at most 8,000 characters and a key at most 250 (`mlflow/utils/validation.py:60` and `:64`, mlflow 3.14.0). The longest value is the list of tools.

What this task does not do. It does not move the two layers out of `app.py`; the proposal leaves that to an item of its own. It adds no run tag that says which layers did not run: the proposal asks for the printed line, and lists the new stored shapes without such a tag. Left out by the plan; say so in the outcome, so the owner can ask for it.

## Acceptance criteria

- [x] `tests/test_eval_runner.py::test_run_carries_the_resolved_recipe` exists and passes: for the recipe `naive_rag` the run opened by the offline driver holds the tags `ema.retrieval.index_profile` with the value `neo4j_hier` and `ema.generation.model`
- [x] `tests/test_eval_runner.py::test_layers_the_runner_does_not_run_are_named` exists and passes: the summary for `regulatory_fewshot` holds one line that names the few-shot layer; the summary for `agentic_judged` holds one line that names the inline judge; the summary for `naive_rag` holds neither
- [x] `grep -c 'cl.user_session' harness/eval/runner.py` prints 0, and `git diff --stat app.py` prints nothing: the two layers are not moved
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]]

## What was built

harness/agents/workflow_adapter.py: read-only property config_attributes (a copy of _extra_attributes). harness/eval/runner.py: recipe_run_tags (every ema.* attribute as a string tag, key <= 250 and value <= 8000 characters, mlflow 3.14.0 validation.py:60/:64) merged into every run that evaluate_items opens, with the explicit run tags taking precedence; layers_not_run gives one 'NOTE: ... runs in app.py only' line for fewshot.enabled and for judge.enabled, added to the report header by run_recipe_benchmark. 2 new tests: a real AgentWorkflowAdapter with a fake session gives a run with ema.retrieval.index_profile=neo4j_hier and ema.generation.model, and its trace carries ema.recipe; regulatory_fewshot prints one few-shot line, agentic_judged one inline-judge line, naive_rag neither. cl.user_session in runner.py: 0; git diff --stat app.py: empty. Left out by the plan, so the owner can ask for it: no run tag records which layers did not run (the proposal asks for the printed line only). make test: 713 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/eval/runner.py`
- `harness/agents/workflow_adapter.py`
- `tests/test_eval_runner.py`
