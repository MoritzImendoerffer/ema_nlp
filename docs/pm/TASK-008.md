---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-008
status: done
kind: mechanism
title: "Post-processing rule 4: take title and reference number from the page header"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-008 — Post-processing rule 4: take title and reference number from the page header

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Proposal step 4; the first look found the header layer left out of Docling's export.

## Acceptance criteria

- [x] `::test_reference_from_page_header` passes: a document whose `EMA/…` reference stands only in a page header gets it at the top of the row's text, where `text_metadata` (first 2,048 characters, `corpus/metadata/text_metadata.py:95`) finds it
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]]

## What was built

Rule 4 in corpus/parsers/docling_post.py: lift_header_reference() uses the build's own EMA_REF_RE (corpus/metadata/text_metadata.py); when the body's first 2,048 characters hold no EMA reference, the first page_header that does (lowest page) is copied into the body as its first item (label text, content_layer body, its provenance kept). Counted as header_reference_lifted. Order of post_process: join, footnote marks and texts, markup, header reference. 2 new tests (18 in tests/test_docling_post.py): text_metadata finds EMA/CHMP/123456/2020 after the lift and not before; no lift when the body holds it. make test-parse 9 passed incl. the lifted line heading DoclingDocument.export_to_markdown(). Gates: make test 813 passed, 3 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- `corpus/parsers/docling_post.py`
- `tests/test_docling_post.py`
