---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-013
status: done
kind: wiring
title: "Pass the profile's passage limit from build_recipe to the two search tools"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-013 — Pass the profile's passage limit from build_recipe to the two search tools

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Why this is a task of its own. TASK-012 adds a key that nothing reads. A profile key without a reader is the defect of `harness/configs/parser_preference.yaml`, which no code reads (`docs/PLANNING_WORKFLOW.md`, rule 1).

The path. `build_recipe` loads the profile (`harness/recipes/build.py:42-46`) and calls `assemble_agent` (lines 81-89). `assemble_agent` passes its keyword arguments to `build_agent` (`harness/agents/session.py:60-70`), which forwards them to every tool builder (`harness/agents/registry.py:51-63`). A builder takes what it knows and ignores the rest through `**_` (`harness/tools/search.py:131`, `harness/tools/corrective_search.py:53`). So one more keyword argument reaches `ema_search` and `corrective_search`, and no other tool changes.

Also pass the value to `recipe.resolved_attributes` at `build.py:102-104`, so that the trace and the run carry the limit that was in force.

The tests build a recipe offline already: `tests/test_recipes.py:153-173` replaces `load_index_profile`, `build_retriever` and `get_llm_for_model`. Use a fake retriever whose nodes carry `matched_text`.

The command that reaches this code with real data is `scripts/run_eval.py`, in TASK-015. `app.py` reaches it on every turn, through the same `build_recipe`.

If the owner chose option (b) or (c) in the decision note, this task changes with TASK-012.

## Acceptance criteria

- [x] `tests/test_recipes.py::test_profile_passage_limit_reaches_ema_search` exists and passes: a recipe built on a profile with `passage_chars: 600` gives an `ema_search` tool whose bodies are at most 600 characters, and the adapter's attributes hold `ema.retrieval.passage_chars` with the value 600
- [x] `tests/test_recipes.py::test_profile_passage_limit_reaches_corrective_search` exists and passes for the recipe `crag_agentic`
- [x] `tests/test_recipes.py::test_build_recipe_wires_agent_from_recipe` and `::test_build_recipe_naive_single_tool` pass
- [x] `grep -c 'passage_chars' harness/recipes/build.py` prints at least 2: the value goes to the tools and to `resolved_attributes`
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-012]]

## What was built

harness/recipes/build.py reads profile.retrieval.passage_chars, passes it to assemble_agent and to recipe.resolved_attributes (grep passage_chars in build.py = 3). harness/agents/session.py: assemble_agent(passage_chars=) forwards it to build_agent only when set (a None would reach the tools' slice as [:None], i.e. no cut); build_agent hands it to every tool builder, and only ema_search and corrective_search read it. tests/test_recipes.py: _fake_profile gains passage_chars; 2 new tests (a profile with 600 gives ema_search bodies <= 600 that start with the leaf, and corrective_search bodies <= 600 for crag_agentic; the adapter's attributes hold ema.retrieval.passage_chars 600). test_build_recipe_wires_agent_from_recipe and test_build_recipe_naive_single_tool pass. Real data, read-only, no model call (Neo4j container healthy, mongod active): build_recipe('naive_rag') on the live graph, one ema_search call for 'nitrosamine acceptable intake limit' in 6.3 s: 9 results, all 9 nodes carry matched_text, all 9 bodies start with the leaf, body lengths 1439-2000, in 7 of 9 the leaf starts after character 400 of its parent (the old cut hid it), passages_from_nodes equals the 9 bodies, ema.retrieval.passage_chars=2000 on the adapter. make test: 729 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/recipes/build.py`
- `harness/agents/session.py`
- `tests/test_recipes.py`
