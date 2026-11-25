---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-011
status: todo
kind: wiring
title: "Expose --prune on the build and the pipeline, and say what --reset deletes"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-011 — Expose --prune on the build and the pipeline, and say what --reset deletes

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

The help text of --reset today says 'DETACH DELETE the graph first' (build.py:41, update_graph.py:96). After TASK-008 it deletes :Document and :Chunk nodes in batches and keeps other nodes. Rule 7 of docs/PLANNING_WORKFLOW.md: a command that deletes appears with its warning in the same block.

The module docstring of build.py shows `--full --reset` as its first example (line 10); put the warning beside it.

## Acceptance criteria

- [ ] `.venv/bin/python -m harness.indexing.build --help` lists --prune, and the help of --reset contains 'Document and Chunk' and 'batches'
- [ ] `tests/test_update_graph.py::test_dry_run_forwards_prune` passes: `update_graph.py --dry-run --steps build --prune` prints a build command that ends with --prune
- [ ] `tests/test_update_graph.py::test_build_cli_forwards_prune` passes: build.main with --prune calls build_index with prune=True (build_index replaced by a recorder)
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-007]], [[TASK-008]]

## Files it touched

- `harness/indexing/build.py`
- `scripts/update_graph.py`
- `tests/test_update_graph.py`
