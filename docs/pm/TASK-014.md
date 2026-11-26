---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-014
status: todo
kind: checkpoint
title: "Checkpoint: write batch 0's decision note and measure the rate on 3 documents"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-014 — Checkpoint: write batch 0's decision note and measure the rate on 3 documents

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Plan choices, overrulable: the 200 are the top of the ranking with at most 60 pages (7,749 pages in the exploration); the 70 are drawn with a fixed seed from the rest with at most 200 pages, so that a few test the page-range path. Exploration section 8: 8.4 to 9.0 hours for the at-most-60-page draw. The 70 random documents are drawn from PDFs that have a legacy row, so that the comparison with today's text exists for each (lead session's review of 2026-11-26).

## Acceptance criteria

- [ ] The note lists the 270 URLs, the seed, the strata sizes counted in the stores, the pages, and the estimated GPU hours with the arithmetic, from a 3-document run in the parse environment
- [ ] It names beforehand the share of tables with numbers missing or added that would stop the batches
- [ ] It cites the owner's yes of 2026-11-25 (about 270 PDFs, 7 to 12 GPU hours, files only); the batch starts only if the estimate stays inside it, and is cut to fit otherwise

**Depends on:** [[TASK-011]], [[TASK-012]], [[TASK-013]]

## Files it touched

- [[2026-11-26_batch-0]] — `docs/pm/decisions/2026-11-26_batch-0.md`
