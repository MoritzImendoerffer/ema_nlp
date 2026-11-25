---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-017
status: done
kind: mechanism
title: "Build the anthropic SDK's response-model serializers before the first traced call"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-017 — Build the anthropic SDK's response-model serializers before the first traced call

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The defect, found 2026-11-23 after TASK-015's first run. The SDK builds responses with construct_type, without validation, so classes with defer_build keep a MockValSer serializer until something calls model_dump on them directly. autolog's CHAT_MODEL span of the parent achat closes before the wrapper's sanitize step and serializes the raw response through mlflow's TraceJSONEncoder (mlflow/tracing/utils/__init__.py:77) -> TypeError 'MockValSer' object is not an instance of 'SchemaSerializer'. Found unbuilt in the live response of claude-opus-4-7: ToolUseBlock, DirectCaller, CacheCreation, OutputTokensDetails (Haiku's response did not fail). Only the first such call of a process fails, since the sanitize step then builds the classes. Reproduced offline with construct_type; model_construct does not reproduce it.

## Acceptance criteria

- [x] `tests/test_llms.py::test_first_traced_response_serializes` passes: in a fresh interpreter, a response built by the SDK's construct_type (tool_use block with caller, usage with cache_creation and output_tokens_details) fails mlflow's dump_span_attribute_value before the warm-up and succeeds after building the wrapper
- [x] One real structured call with claude-opus-4-7 under autolog in a fresh process, to a scratch store, logs no 'Failed to end span'
- [x] `make test` passes and `make lint` passes, each run on its own line

## What was built

harness/llms.py: warm_anthropic_models() builds every unbuilt pydantic class of the loaded anthropic.types modules (model_rebuild(force=True)), once per process (382 classes, 0.09 s; second call 0); _make_anthropic calls it before the first traced call. Cause found with 3 short structured calls of claude-opus-4-7 to a scratch store (Haiku did not fail) and mlflow's debug traceback: TraceJSONEncoder.default -> model_dump -> TypeError 'MockValSer'; unbuilt in the live response: ToolUseBlock, DirectCaller, CacheCreation, OutputTokensDetails. Reproduced offline only with the SDK's construct_type (model_construct does not). New test test_first_traced_response_serializes runs in a fresh interpreter (2.4 s): BEFORE the dump fails with MockValSer, AFTER _make_anthropic it is OK (skips if a library upgrade removes the defect). Real check: the same structured call with claude-opus-4-7 after the fix logged 0 'Failed to end span', and the trace holds the _Anthropic.achat CHAT_MODEL span that T1's trace lacked. make test: 736 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/llms.py`
- `tests/test_llms.py`
