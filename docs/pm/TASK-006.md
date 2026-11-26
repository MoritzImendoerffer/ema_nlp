---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-006
status: todo
kind: mechanism
title: "Post-processing rule 2: footnote marks stay marks, footnote texts attach to their table"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-006 — Post-processing rule 2: footnote marks stay marks, footnote texts attach to their table

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Exploration section 4: PaddleOCR-VL writes marks as superscript markup (`FAS\(^{a}\)`), and Docling 2.153.0 exports the footnotes under the repatha table, which 2.132.0 drops.

## Acceptance criteria

- [ ] `::test_footnote_mark_is_not_merged_into_number` passes: a cell `12.5\(^{1}\)` becomes the value 12.5 with the mark 1, never 12.51
- [ ] `::test_footnote_texts_attach_to_table` passes: texts below a table that begin with a mark used in its cells are attached to that table
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]]

## Files it touched

- `corpus/parsers/docling_post.py`
- `tests/test_docling_post.py`
