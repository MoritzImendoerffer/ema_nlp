---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-010
status: done
kind: mechanism
title: "Write the ranking script: complex-table score and page count per PDF"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-010 — Write the ranking script: complex-table score and page count per PDF

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The rule is the proposal's (section 'The batches'); exploration section 6 counted 16,633 documents under it, against the review's 5,424 under a stricter rule. Page counts come from the cache (the exploration's count took 567 s with 4 processes).

## Acceptance criteria

- [x] `tests/test_rank_pdfs_by_tables.py` passes: the score of a document is the number of cells in its tables with 8 or more columns, 20 or more rows, or ragged rows; a table needs a separator line
- [x] The script writes a ranked JSONL to `config.RESULTS_DIR` with url, score, pages, cache_path, gzip, and documents with pages without text listed after the scored ones
- [x] Run read-only on the stores: it reports 58,121 legacy PDF rows and 16,633 with a score above 0 (the exploration's count)
- [x] `make test` passes and `make lint` passes, each run on its own line

## What was built

scripts/rank_pdfs_by_tables.py: score = cells in Markdown tables (a separator line required) with 8+ columns, 20+ rows or ragged rows, from the legacy pymupdf4llm row; pages, pages without text (<50 characters) and the gzip flag from the Scrapy cache (pymupdf, 4 processes); order: score descending, then documents with pages without text (most first), then the rest by URL; one JSONL (url, score, tables, complex_tables, cache_path, pages, pages_without_text, gzip, cache_error, rank, tier) under RESULTS_DIR/docling/. Full read-only run, 450 s: legacy_rows 58121, score_above_0 16633, pages_without_text_tier 2726, others 38762, cache_errors 0, pages 919404 -> RESULTS_DIR/docling/ranking_2026-11-26.jsonl; all 58,121 scores equal the exploration's count; the top 200 of at most 60 pages hold 7,749 pages (scores 4,962 to 10,975). None of the legacy rows points to a gzip body (the 6,833 gzip bodies belong to PDFs without a legacy row). Exploration section 6's 'up to 10,975' corrected to 69,305; section 12.2 added. tests/test_rank_pdfs_by_tables.py 6 passed. Gates: make test 835 passed, 3 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- `scripts/rank_pdfs_by_tables.py`
- `tests/test_rank_pdfs_by_tables.py`
