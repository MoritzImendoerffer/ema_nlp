---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-012
status: done
kind: mechanism
title: "Write the batch report: rates, failures, sizes, post-processing counts, table numbers, words held"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-012 — Write the batch report: rates, failures, sizes, post-processing counts, table numbers, words held

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Proposal section 'What batch 0 reports'. The check cannot see a number in the wrong cell; the page says so.

## Acceptance criteria

- [x] The report gives seconds per page for pages without tables, seconds per table and per cell, for the ranked and the random group separately, each with n
- [x] It lists every failed or partial document, the bytes per page of each file plain and gzip, and the counts of tables joined, footnotes attached and markup converted
- [x] The table-number check: for each table on a page with a text layer, the share of the text layer's numbers inside the table's box that the cells hold, and the share of the cells' numbers that the text layer holds
- [x] Words and numbers held against the legacy text of the same document
- [x] `tests/test_report_docling_batch.py` passes on two stored fixture documents
- [x] `make test` passes and `make lint` passes, each run on its own line
- [x] It counts CJK characters returned by OCR per document (exploration section 12)
- [x] Beside numbers: Greek letters and the micro sign held against the text layer, for the page text and for the tables, each with n, and the Greek letters returned that the layer lacks; a Greek letter on a line without a run of 3 or more Greek letters counts as a symbol in Latin text (the lead session's line rule of 2026-11-26), and the page states the rule
- [x] Table numbers: a pair where the text-layer number equals the cell's number followed by its mark's digits (layer 12.51, cell 12.5[^1]) is counted in its own column and kept out of both the held and the missed shares (lead session's review, 2026-11-26)

**Depends on:** [[TASK-009]]

## What was built

scripts/report_docling_batch.py (runs in .venv; reads doc.json as JSON, the PDF text layer with pymupdf, the legacy rows read-only) writes report_<list>.json and .md under RESULTS_DIR/docling. Per group with n: seconds per page (all; documents without tables) and a least-squares fit seconds = a x pages without tables + b x tables + c x cells (n >= 3). Failures without a folder, with cause; parsed after an earlier failure counted. Bytes per page of each file plain and gzip. Post-processing counts. Table numbers per table on a page with a text layer (>= 50 characters): layer numbers inside the table's boxes held by the cells and cell numbers held by the layer; pairs where the layer flattened a footnote mark (layer 12.51, cell 12.5[^1]) counted in their own column and left out of both shares (lead session's review). Greek letters by the lead session's line rule (no run of 3+ Greek letters = symbol in Latin text), for page text and tables: symbols held, of which μ, Greek-language letters held, Greek letters returned that the layer lacks; the page states the rule; NFKC so µ = μ. CJK per document. Words and numbers held against the legacy text. Fixtures: tests/fixtures/docling/batch/ (the two parses the batch command made in the parse env). tests/test_report_docling_batch.py 5 passed (two fixture documents: 5 tables checked, 42 of 42 layer numbers held; failure listed; fit recovers 0.5/2.0/0.1; flattened pair; line rule). Ran as a command on the fixture list. Gates: make test 840 passed, 3 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- `scripts/report_docling_batch.py`
- `tests/test_report_docling_batch.py`
