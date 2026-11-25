---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-012
status: todo
kind: mechanism
title: "Write the backfill that stamps the parse identity on existing documents"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-012 — Write the backfill that stamps the parse identity on existing documents

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

The proposal: 'A backfill script sets them from the row that the old rule picked, without touching a chunk.' Old rule = the first clean row the cursor yields per URL (TASK-002's `old_rule`). For all 80,078 clean URLs today the old-rule row and the selected row are the same row (5 URLs have two rows; their second row is an unlisted llamahub fixture), so the printed difference count should be 0.

It stamps only `WHERE d.text_sha256 IS NULL`, in UNWIND batches through graph_ops.stamp_parse_identity, so it can stop and resume. It hashes the text of every row: 1,979 MB of data in parsed_documents. It never writes a chunk, an edge or a Mongo row.

`--verify` repeats the exploration's 80-of-80 check (section 4.3) on a sample: build_ingested_doc of the row gives exactly the chunk ids that `MATCH (d:Document {id: $id})-[:HAS_CHUNK]->(c)` returns.

No live run in this task: that is TASK-016, after the owner's yes.

## Acceptance criteria

- [ ] `tests/test_backfill_parse_identity.py::test_backfill_stamps_old_rule_row` passes: a graph document without the values gets the parser, version and text hash of its old-rule row
- [ ] `::test_backfill_is_resumable` passes: a second run stamps 0 documents
- [ ] `::test_backfill_dry_run_writes_nothing` passes
- [ ] `::test_verify_compares_chunk_ids` passes: `--verify N` rebuilds the chunk ids of N sampled documents and prints 'verify: k of N equal'
- [ ] The script prints how many URLs have an old-rule row that differs from the selected row
- [ ] `.venv/bin/python scripts/backfill_parse_identity.py --help` exits 0
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-002]], [[TASK-003]], [[TASK-005]]

## Files it touched

- `scripts/backfill_parse_identity.py`
- `tests/test_backfill_parse_identity.py`
