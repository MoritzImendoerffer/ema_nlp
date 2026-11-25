---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-011
status: done
kind: wiring
title: "Expose --prune on the build and the pipeline, and say what --reset deletes"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-011 — Expose --prune on the build and the pipeline, and say what --reset deletes

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The help text of --reset today says 'DETACH DELETE the graph first' (build.py:41, update_graph.py:96). After TASK-008 it deletes :Document and :Chunk nodes in batches and keeps other nodes. Rule 7 of docs/PLANNING_WORKFLOW.md: a command that deletes appears with its warning in the same block.

The module docstring of build.py shows `--full --reset` as its first example (line 10); put the warning beside it.

## Acceptance criteria

- [x] `.venv/bin/python -m harness.indexing.build --help` lists --prune, and the help of --reset contains 'Document and Chunk' and 'batches'
- [x] `tests/test_update_graph.py::test_dry_run_forwards_prune` passes: `update_graph.py --dry-run --steps build --prune` prints a build command that ends with --prune
- [x] `tests/test_update_graph.py::test_build_cli_forwards_prune` passes: build.main with --prune calls build_index with prune=True (build_index replaced by a recorder)
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-007]], [[TASK-008]]

## What was built

harness/indexing/build.py: --prune (forwarded as prune=True), --reset help 'DELETE every Document and Chunk node first, in batches (other nodes stay)', --no-resume help 'replace every document', and a docstring whose --reset example carries its WARNING (rule 7). scripts/update_graph.py: --prune forwarded to the build step, --reset help, and a refresh example without --reset beside a warned --reset example. 3 tests in tests/test_update_graph.py (dry run forwards --prune; build.main passes prune=True; --help names 'Document and Chunk' and 'batches'). Gates: make test 778 passed, 2 skipped, 7 deselected (33 warnings: the 2 new ones are a library load_module() DeprecationWarning raised when the CLI test imports harness.indexing); make lint All checks passed.

## Files it touched

- `harness/indexing/build.py`
- `scripts/update_graph.py`
- `tests/test_update_graph.py`
