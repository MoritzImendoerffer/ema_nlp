---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-008
status: todo
kind: mechanism
title: "Post-processing rule 4: take title and reference number from the page header"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-008 — Post-processing rule 4: take title and reference number from the page header

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Proposal step 4; the first look found the header layer left out of Docling's export.

## Acceptance criteria

- [ ] `::test_reference_from_page_header` passes: a document whose `EMA/…` reference stands only in a page header gets it at the top of the row's text, where `text_metadata` (first 2,048 characters, `corpus/metadata/text_metadata.py:95`) finds it
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]]

## Files it touched

- `corpus/parsers/docling_post.py`
- `tests/test_docling_post.py`
