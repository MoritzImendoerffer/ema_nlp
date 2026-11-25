---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-016
status: done
kind: mechanism
title: "Send the workspace header on every Anthropic request when ANTHROPIC_WORKSPACE_ID is set"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-016 — Send the workspace header on every Anthropic request when ANTHROPIC_WORKSPACE_ID is set

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Added on 2026-11-23 on the owner's choice (b) in the decision note. The key in the credentials file is organization-scoped, and the API answered the free model listing with 400 'This API key is not scoped to a workspace, so this request must include the anthropic-workspace-id header'. The installed anthropic SDK 0.105.2 has no setting for it. Installed APIs that carry the header: llama-index-llms-anthropic 0.11.5 Anthropic(default_headers=...) (base.py:229); anthropic.Anthropic(default_headers=...); mlflow 3.14.0 make_judge(extra_headers=...) (make_judge.py:121, gateway_adapter.py:553-554). Unset variable: no header, no behaviour change. Not verified offline: whether the configured endpoint passes the header on; the free listing checks that.

## Acceptance criteria

- [x] `tests/test_models.py::test_workspace_header_only_when_the_variable_is_set` passes: no variable gives {}, a set variable gives {'anthropic-workspace-id': <value>}
- [x] `tests/test_models.py::test_call_anthropic_sends_the_workspace_header` passes: the client of _call_anthropic is built with the header
- [x] `tests/test_llms.py::test_agent_model_sends_the_workspace_header` passes: the LlamaIndex Anthropic client built by _make_anthropic carries the header, and carries none when the variable is unset
- [x] `tests/test_eval_judges.py::test_anthropic_judge_sends_the_workspace_header` passes: build_judge passes extra_headers with the header for an anthropic model, and none for an openai model
- [x] With the owner's workspace ID in the credentials file, the free model listing through the configured endpoint returns the model ids, among them claude-opus-4-7 and claude-opus-5-5
- [x] `make test` passes and `make lint` passes, each run on its own line

## What was built

harness/models.py: WORKSPACE_ENV / WORKSPACE_HEADER and anthropic_headers() ({'anthropic-workspace-id': ANTHROPIC_WORKSPACE_ID} when set, else {}), read at call time; _call_anthropic builds its client with default_headers. harness/llms.py: _make_anthropic passes default_headers to LlamaIndex Anthropic (both its sync and async client carry the header). harness/eval/judges.py: build_judge passes extra_headers for an anthropic model (mlflow 3.14.0 make_judge.py:121, gateway_adapter.py:553). harness/configs/models.yaml comment names the variable. 4 new tests. Unset variable: no header. Real check, free: with the owner's workspace ID in the credentials file, GET /v1/models through the configured endpoint listed 15 models, among them claude-opus-4-7 and claude-opus-5-5 (it had answered 400 'not scoped to a workspace' without the header). Listing workspaces with this key is not permitted (403). make test: 733 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/models.py`
- `harness/llms.py`
- `harness/eval/judges.py`
- `harness/configs/models.yaml`
- `tests/test_models.py`
- `tests/test_llms.py`
- `tests/test_eval_judges.py`
