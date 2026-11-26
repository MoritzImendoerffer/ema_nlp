---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-010
status: todo
kind: mechanism
title: "Write the ranking script: complex-table score and page count per PDF"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-010 — Write the ranking script: complex-table score and page count per PDF

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

The rule is the proposal's (section 'The batches'); exploration section 6 counted 16,633 documents under it, against the review's 5,424 under a stricter rule. Page counts come from the cache (the exploration's count took 567 s with 4 processes).

## Acceptance criteria

- [ ] `tests/test_rank_pdfs_by_tables.py` passes: the score of a document is the number of cells in its tables with 8 or more columns, 20 or more rows, or ragged rows; a table needs a separator line
- [ ] The script writes a ranked JSONL to `config.RESULTS_DIR` with url, score, pages, cache_path, gzip, and documents with pages without text listed after the scored ones
- [ ] Run read-only on the stores: it reports 58,121 legacy PDF rows and 16,633 with a score above 0 (the exploration's count)
- [ ] `make test` passes and `make lint` passes, each run on its own line

## Files it touched

- `scripts/rank_pdfs_by_tables.py`
- `tests/test_rank_pdfs_by_tables.py`
