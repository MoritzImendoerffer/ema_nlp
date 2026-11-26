---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-014
status: done
kind: mechanism
title: "Fix the delete and reset batch sizes from the measurement"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-014 — Fix the delete and reset batch sizes from the measurement

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

A separate task so that the measurement records numbers and this task changes code: the measurement page is the reason for the constants.

## Acceptance criteria

- [x] The batch-size constants in harness/indexing/graph_ops.py equal the values that docs/eval/2026-11-25_graph_delete_measurement.md recommends, and a comment beside each links that page
- [x] If the page says that one document's replace needs batching, delete_document_chunks batches; a test asserts the batch clause
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-013]]

## What was built

The measurement page recommends 10,000 rows for the per-document chunk delete and for the reset, equal to the provisional values, so CHUNK_DELETE_BATCH_ROWS and RESET_BATCH_ROWS in harness/indexing/graph_ops.py stay 10,000; their comment now cites docs/eval/2026-11-25_graph_delete_measurement.md with the numbers. delete_document_chunks already batched; test_default_batch_sizes_follow_the_measurement asserts the constants and the 'IN TRANSACTIONS OF 10000 ROWS' clause of both defaults. Gates: make test 786 passed, 2 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- `harness/indexing/graph_ops.py`
- `harness/indexing/property_graph.py`
