---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-012
status: todo
kind: mechanism
title: "Write the batch report: rates, failures, sizes, post-processing counts, table numbers, words held"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-012 — Write the batch report: rates, failures, sizes, post-processing counts, table numbers, words held

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Proposal section 'What batch 0 reports'. The check cannot see a number in the wrong cell; the page says so.

## Acceptance criteria

- [ ] The report gives seconds per page for pages without tables, seconds per table and per cell, for the ranked and the random group separately, each with n
- [ ] It lists every failed or partial document, the bytes per page of each file plain and gzip, and the counts of tables joined, footnotes attached and markup converted
- [ ] The table-number check: for each table on a page with a text layer, the share of the text layer's numbers inside the table's box that the cells hold, and the share of the cells' numbers that the text layer holds
- [ ] Words and numbers held against the legacy text of the same document
- [ ] `tests/test_report_docling_batch.py` passes on two stored fixture documents
- [ ] `make test` passes and `make lint` passes, each run on its own line
- [ ] It counts CJK characters returned by OCR per document (exploration section 12)
- [ ] Beside numbers: Greek letters and the micro sign held against the text layer, for the page text and for the tables, each with n, and the Greek letters returned that the layer lacks; a Greek letter on a line without a run of 3 or more Greek letters counts as a symbol in Latin text (the lead session's line rule of 2026-11-26), and the page states the rule

**Depends on:** [[TASK-009]]

## Files it touched

- `scripts/report_docling_batch.py`
- `tests/test_report_docling_batch.py`
