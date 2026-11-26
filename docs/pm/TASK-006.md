---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-006
status: done
kind: mechanism
title: "Post-processing rule 2: footnote marks stay marks, footnote texts attach to their table"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-006 — Post-processing rule 2: footnote marks stay marks, footnote texts attach to their table

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Exploration section 4: PaddleOCR-VL writes marks as superscript markup (`FAS\(^{a}\)`), and Docling 2.153.0 exports the footnotes under the repatha table, which 2.132.0 drops.

## Acceptance criteria

- [x] `::test_footnote_mark_is_not_merged_into_number` passes: a cell `12.5\(^{1}\)` becomes the value 12.5 with the mark 1, never 12.51
- [x] `::test_footnote_texts_attach_to_table` passes: texts below a table that begin with a mark used in its cells are attached to that table
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]]

## What was built

Rule 2 in corpus/parsers/docling_post.py: superscript_marks() writes \(^{1}\) and ^{a} as Unicode superscripts (12.5\(^{1}\) -> 12.5¹, FAS\(^{a}\) -> FASᵃ), leaves exponents after a mantissa (2.06e^{-14}, 10^{3}) for rule 3, and writes a mark without a superscript form as ^x; attach_table_footnotes() collects the trailing marks of each table's cells and attaches the body texts directly below the table that begin with one of those marks (parent set to the table, ref moved from body children to the table's footnotes and children); a text with another mark or no mark ends the scan. Counts footnote_marks and footnotes_attached. 4 new tests (11 in tests/test_docling_post.py); synthetic fixtures given valid boxes and orientation so they load in docling-core. make test-parse: 8 passed incl. the attached footnote loading as a DoclingDocument with 'FASᵃ' in its Markdown. Gates: make test 806 passed, 3 skipped, 13 deselected; make lint All checks passed (after ruff --fix of one parenthesis). Revised 2026-11-26 after the lead session's review: a Unicode superscript does not survive NFKC/NFKD ("12.5¹" -> "12.51"), so a mark is now written as a Markdown footnote reference, "12.5[^1]", and an attached footnote text as a definition, "[^1]: ..." (also for footnotes Docling attached itself). Unit exponents are not marks: a signed superscript or a digit after a length unit is written with a caret (1.73 m^2, mL min^-1). No mark field in the cell: docling-core 2.108.0's TableCell ignores extra fields, so it would vanish on any load and export.

## Files it touched

- `corpus/parsers/docling_post.py`
- `tests/test_docling_post.py`
