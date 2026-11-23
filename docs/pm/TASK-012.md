---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-012
status: done
kind: contract
title: "Make the passage limit a key of the index profile, and stamp it on the trace"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-012 — Make the passage limit a key of the index profile, and stamp it on the trace

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

This task waits on the owner. The proposal says 'a limit set in the tool's config', and no tool has a config file: `harness/configs/` has no `tools/` folder, and a tool receives its arguments from `assemble_agent` (`harness/agents/session.py:59-70`). `exploration.md` section 11, question 2, puts the choice to the owner. The decision note gives the three options.

The task is written for option (a), the assistant's recommendation: a key `passage_chars` in the `retrieval` block of the index profile, beside `k` and `merge`. If the owner chooses the recipe (b) or a new tool config file (c), the files and the tests of this task and of TASK-013 change. Do not improvise: correct the plan first.

The stored shape, for option (a). `RetrievalConfig` (`harness/indexing/profiles.py:188-225`) gets `passage_chars: int`, parsed and validated in `from_dict` the way `k` is (lines 207-209). The three profiles under `harness/configs/index/` state the key, so a reader sees it. The profiles are authored data: edit them by hand in the commit of this task.

What happens to what exists. A profile without the key reads as 2,000, so a profile in a `$EMA_CONFIG_DIR` written earlier keeps working. Nothing is stored in Mongo or in the graph. A trace made before this task has no `ema.retrieval.passage_chars`; read its absence as the 400-character cut.

Why the limit goes on the trace. Two runs with different limits give the agent different text, so their numbers do not compare. `Recipe.resolved_attributes` already stamps `retrieval.k` when it is supplied (`harness/recipes/config.py:186-187`); do the same for the limit. TASK-008 copies these attributes to the run.

One default, defined once. TASK-011 defines the constant for the tool builders. This task makes the profile's default the same constant, not a second literal.

No caller yet: TASK-013 passes the profile's value to the tools.

## Acceptance criteria

- [x] Before any edit: `grep -c '^status: settled' docs/pm/decisions/2026-11-23_passage-limit-location.md` prints 1, and the note's answer is option (a). If it prints 0, stop: the task waits on the owner. If the answer is (b) or (c), stop: this task is written for (a) and the plan has to be corrected first
- [x] `tests/test_indexing_profiles.py::test_passage_chars_defaults_to_2000_and_must_be_positive` exists and passes: a profile without the key gives 2000; the value 0 raises `ValueError`
- [x] `for f in neo4j_hier neo4j_steered neo4j_tree; do grep -c 'passage_chars' harness/configs/index/$f.yaml; done` prints at least 1 three times
- [x] `tests/test_recipes.py::test_resolved_attributes_stamp_the_passage_limit` exists and passes: `resolved_attributes(passage_chars=600)` holds `ema.retrieval.passage_chars` with the value 600, and the call without the argument has no such key
- [x] `grep -rn '2000' harness/tools/search.py harness/indexing/profiles.py | grep -ci 'passage'` prints 1: the default is defined once and read by both modules
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-011]]

## What was built

Decision note settled by the owner on 2026-11-23 ('agree', option (a)); grep '^status: settled' = 1. harness/indexing/profiles.py: RetrievalConfig.passage_chars, default DEFAULT_PASSAGE_CHARS imported from harness/tools/search.py (the literal is defined once: grep 2000 + passage over the two files = 1), parsed in from_dict, ValueError when <= 0. The three profiles neo4j_hier, neo4j_steered and neo4j_tree state passage_chars: 2000 (authored data, edited by hand). Recipe.resolved_attributes(passage_chars=) stamps ema.retrieval.passage_chars only when supplied. A profile without the key (e.g. an older one under $EMA_CONFIG_DIR) reads as 2000; a trace made before this work has no ema.retrieval.passage_chars and means the 400-character cut. 2 new tests. No caller yet: TASK-013. make test: 727 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/indexing/profiles.py`
- `harness/configs/index/neo4j_hier.yaml`
- `harness/configs/index/neo4j_steered.yaml`
- `harness/configs/index/neo4j_tree.yaml`
- `harness/recipes/config.py`
- `tests/test_indexing_profiles.py`
- `tests/test_recipes.py`
