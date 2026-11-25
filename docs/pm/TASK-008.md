---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-008
status: todo
kind: mechanism
title: "Make the reset delete corpus nodes in batches and keep every other node"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-008 — Make the reset delete corpus nodes in batches and keep every other node

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Defect 5 of the proposal: `reset=True` runs `MATCH (n) DETACH DELETE n` (property_graph.py:453) on 7.5 million nodes and 14.6 million relationships in one transaction, with a 2 GB heap and `dbms.memory.transaction.total.max` 1.40 GiB. It also deletes the NeoDash dashboard node (one node, label `_Neodash_Dashboard` only).

Delete :Chunk first, then :Document, through graph_ops.reset_corpus, in batches. Start with 10,000 rows per transaction as a module constant; TASK-014 fixes it from the measurement.

The reset is not run on the live graph in this item (proposal: 'It makes the reset safe to run; running it is the owner's decision').

## Acceptance criteria

- [ ] `tests/test_indexing_property_graph.py::test_reset_keeps_other_nodes` passes on the in-memory double: a node labelled _Neodash_Dashboard survives, no :Document or :Chunk remains
- [ ] `grep -rn 'MATCH (n) DETACH DELETE n' harness/ scripts/` prints nothing
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]]

## Files it touched

- `harness/indexing/property_graph.py`
- `tests/test_indexing_property_graph.py`
