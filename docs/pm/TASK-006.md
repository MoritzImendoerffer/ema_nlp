---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-006
status: done
kind: mechanism
title: "Map each provider of models.yaml to the name, the key and the endpoint that an mlflow judge needs"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-006 — Map each provider of models.yaml to the name, the key and the endpoint that an mlflow judge needs

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The defect. `judge_model_uri` (`harness/eval/judges.py:101-105`) raises for every provider other than `anthropic`. Decision B of the proposal makes the judge a setting, so each provider of `models.yaml` has to resolve.

What mlflow 3.14.0 needs, read in `mlflow/metrics/genai/model_utils.py`.
- `together_ai` of `models.yaml` is `togetherai` for mlflow. mlflow reads the key from `TOGETHERAI_API_KEY` (line 430). This repository sets `TOGETHER_API_KEY` (`harness/models.py:133`).
- `openai_compatible` is `openai` for mlflow. mlflow requires `OPENAI_API_KEY` (lines 349-354) and reads the endpoint from `OPENAI_API_BASE` or `OPENAI_BASE_URL` (lines 356-357). A `base_url` passed to `make_judge` is used as the endpoint verbatim (`mlflow/genai/judges/adapters/gateway_adapter.py:546`), so for this provider it must end in `/chat/completions`. The entry names its own key variable in `api_key_env` (`local_qwen32` names `LOCAL_LLM_API_KEY`).
- `is_supported_provider` returns False for `together_ai` and `openai_compatible`. A name mlflow does not know fails on the first judge call, not when the judge is built, so raise when the route is resolved.

What to build. A loader in `harness/models.py` that returns the `ModelConfig` of a model key; today only `load_model_for_role` exists (line 56). A pure function in `harness/eval/judges.py` that turns a `ModelConfig` into the mlflow model name, the endpoint, and which variable of this repository supplies which variable mlflow reads. `judge_model_uri` resolves a role, or a model key when one is given. `ema_judges` applies the route when it builds the judges: it copies the key inside the process and passes the endpoint as `base_url`. Log the names of the variables, never a value.

A risk to state in the docstring. Copying `LOCAL_LLM_API_KEY` to `OPENAI_API_KEY` replaces an OpenAI key in the process for the rest of the run. Nothing else in this repository reads `OPENAI_API_KEY` except as the default of `api_key_env` (`harness/llms.py`, `harness/models.py:137`).

Not verified by this task, and not by this work unit: a real judge call to a provider other than `anthropic`. `TOGETHER_API_KEY`, `TOGETHERAI_API_KEY`, `OPENAI_API_KEY` and `LOCAL_LLM_API_KEY` are all unset on this machine on 2026-11-23. The proposal says so too. These routes are tested up to the model name, the key and the endpoint.

The Anthropic route stays as it is: `_anthropic_judge_base_url` appends `/v1/messages` when `ANTHROPIC_BASE_URL` is set (`judges.py:61-71`).

Caller: `run_recipe_benchmark` calls `judge_model_uri` and `ema_judges` already. TASK-007 adds the option that selects a model key.

## Acceptance criteria

- [x] `tests/test_eval_judges.py::test_judge_model_uri_for_each_provider_of_models_yaml` exists and passes: `anthropic:/claude-sonnet-5` for the entry `claude_sonnet`, `togetherai:/allenai/OLMo-2-1124-32B-Instruct` for `olmo_32b`, `openai:/Qwen/Qwen2.5-32B-Instruct` for `local_qwen32`
- [x] `tests/test_eval_judges.py::test_judge_model_uri_raises_for_a_provider_mlflow_cannot_serve` exists and passes: a model entry with the provider `no_such_provider` raises `ValueError`, and the message names that provider
- [x] `tests/test_eval_judges.py::test_judge_route_maps_the_key_and_the_endpoint` exists and passes: for `olmo_32b` the value of `TOGETHER_API_KEY` is what mlflow will read as `TOGETHERAI_API_KEY`; for `local_qwen32` the endpoint is `http://localhost:8000/v1/chat/completions` and the value of `LOCAL_LLM_API_KEY` is what mlflow will read as `OPENAI_API_KEY`. The test sets the variables with `monkeypatch.setenv` and prints no value
- [x] `tests/test_models.py::test_load_model_config_by_key` exists and passes: the key `claude_sonnet` gives the model id `claude-sonnet-5`, and an unknown key raises `ValueError`
- [x] `tests/test_eval_judges.py::test_judge_model_uri_resolves_role_from_models_yaml` and `::test_anthropic_judge_base_url` pass unchanged
- [x] `make test` passes and `make lint` passes, each run on its own line; the outcome says that no judge call to a provider other than `anthropic` was made

## What was built

harness/models.py: load_model_config(model_name) returns the ModelConfig of a models: key (ValueError for an unknown key); load_model_for_role shares the builder. harness/eval/judges.py: JudgeRoute(model, base_url, key_env), judge_route(cfg) (anthropic -> anthropic; together_ai -> togetherai with TOGETHER_API_KEY -> TOGETHERAI_API_KEY; openai_compatible -> openai with api_base + '/chat/completions' and api_key_env -> OPENAI_API_KEY; ValueError naming any other provider), resolve_judge_route(role, model_key=), apply_judge_key(route) (copies the key inside the process, logs variable names only), judge_model_uri(role, model_key=), and ema_judges(model= | route=). run_recipe_benchmark builds its judges with ema_judges(route=resolve_judge_route(judge_role)). 4 new tests; test_judge_model_uri_resolves_role_from_models_yaml and test_anthropic_judge_base_url pass unchanged. No judge call to a provider other than anthropic was made: TOGETHER_API_KEY, TOGETHERAI_API_KEY, OPENAI_API_KEY and LOCAL_LLM_API_KEY are unset here, so those routes are tested up to model name, key variable and endpoint. make test: 708 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/eval/judges.py`
- `harness/models.py`
- `tests/test_eval_judges.py`
- `tests/test_models.py`
