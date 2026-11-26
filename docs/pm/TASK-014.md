---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-014
status: done
kind: checkpoint
title: "Checkpoint: write batch 0's decision note and measure the rate on 3 documents"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-014 — Checkpoint: write batch 0's decision note and measure the rate on 3 documents

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Plan choices, overrulable: the 200 are the top of the ranking with at most 60 pages (7,749 pages in the exploration); the 70 are drawn with a fixed seed from the rest with at most 200 pages, so that a few test the page-range path. Exploration section 8: 8.4 to 9.0 hours for the at-most-60-page draw. The 70 random documents are drawn from PDFs that have a legacy row, so that the comparison with today's text exists for each (lead session's review of 2026-11-26).

## Acceptance criteria

- [x] The note lists the 270 URLs, the seed, the strata sizes counted in the stores, the pages, and the estimated GPU hours with the arithmetic, from a 3-document run in the parse environment
- [x] It names beforehand the share of tables with numbers missing or added that would stop the batches
- [x] It cites the owner's yes of 2026-11-25 (about 270 PDFs, 7 to 12 GPU hours, files only); the batch starts only if the estimate stays inside it, and is cut to fit otherwise
- [x] It names beforehand the share of Greek symbols held that would stop the batches, quoting the owner's requirement "Greek symbols should be conserved" (relayed by the lead session, 2026-11-26)

**Depends on:** [[TASK-011]], [[TASK-012]], [[TASK-013]]

## What was built

Decision note docs/pm/decisions/2026-11-26_batch-0.md (status settled: the owner's yes of 2026-11-25 relayed by the lead session, and the lead's instruction G). Strata counted from the ranking (MongoDB + cache, read-only): 58,121 legacy rows; tier 1 16,633; tier 1 at most 60 pages 13,585 -> ranked = first 200 (ranks 1-401, scores 4,962-10,975, 7,749 pages); random pool 57,722 (at most 200 pages, not in the 200) -> 70 drawn with random.Random(20261126).sample (890 pages; tiers 17/2/51). The 3-document rate run (rate3.jsonl, 250 W cap): 30 pages, 0 failures, 414.6 s; stage timings: table stage 0.058 s per cell (pandemrix: 289.4 s for 4,982 cells), OCR 0.85 s/page there, but 108 s for 10 pages of speakers-biography (36 photographs; Docling OCRs bitmap regions on text-layer pages; RapidOCR on CPU). Estimate for all 270: 23.2 h ranked + 2.54 h random + overhead = about 26 h, outside the 12 h; cut to fit: random 70 first, then ranked in rank order, stop-file timer at 11 h 00 min (estimate: 126 documents, 56 ranked, 3,502 pages, 10.98 h); worker test on the 20 random documents with the fewest pages (33 pages) with 2 and 3 workers, 20 min timers. Stop thresholds named beforehand: tables missing/adding numbers > 20%; numbers held < 98% either way; Greek symbols held < 98% page text or < 90% tables (n >= 20), quoting "Greek symbols should be conserved"; failures > 5%; any document > 10 CJK characters. The full-corpus estimate moves to 16-113 days (proposal: 25-46), noted for TASK-017. The note lists the 270 URLs in run order with per-document estimates. The report gained the share of tables with numbers missing or added (the threshold's measure). Gates: make test 840 passed, 3 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- [[2026-11-26_batch-0]] — `docs/pm/decisions/2026-11-26_batch-0.md`
