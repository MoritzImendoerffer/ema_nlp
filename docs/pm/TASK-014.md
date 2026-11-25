---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-014
status: todo
kind: mechanism
title: "Fix the delete and reset batch sizes from the measurement"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-014 — Fix the delete and reset batch sizes from the measurement

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

A separate task so that the measurement records numbers and this task changes code: the measurement page is the reason for the constants.

## Acceptance criteria

- [ ] The batch-size constants in harness/indexing/graph_ops.py equal the values that docs/eval/2026-11-25_graph_delete_measurement.md recommends, and a comment beside each links that page
- [ ] If the page says that one document's replace needs batching, delete_document_chunks batches; a test asserts the batch clause
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-013]]

## Files it touched

- `harness/indexing/graph_ops.py`
- `harness/indexing/property_graph.py`
