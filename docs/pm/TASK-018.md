---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-018
status: done
kind: measurement
title: "Measure the OCR recognition models on pages with a known answer, and choose one"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-018 — Measure the OCR recognition models on pages with a known answer, and choose one

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Required by the lead session's review of 2026-11-26 before TASK-004 fixes the model. The exploration's switch rested on one wrong character in one document, and 'no CJK character' is a weak test: a model that cannot write CJK passes it by construction. The larger risk is µg read as ug or mg, which changes a dose. OCR touches 30,614 pages in 5,503 documents (exploration section 6). CPU work of minutes; no approval needed. Addendum 12.1 (2026-11-26): the PP-OCRv5 and PP-OCRv4 server recognizers, EasyOCR (no Greek model) and Nemotron OCR v2 all read worse; Tesseract, measured by the lead session, cannot correct the Greek symbols. The choice stands.

## Acceptance criteria

- [x] About 30 pages with a text layer from about 10 cached PDFs, chosen so that they hold µ, ±, ≥, ≤, °, × and Greek letters; the page list and the rule written down
- [x] Each recognition model OCRs the whole page image: the multilingual PP-OCRv6 small model, en_PP-OCRv5_rec_mobile, and any other English or Latin recognition model that rapidocr 3.10.0 offers
- [x] Against the text layer: the share of words, of numbers and of each symbol held, and the CJK characters returned, per model, each with n
- [x] The choice and the numbers go into an addendum of exploration.md and into the plan's choices; if the English model loses symbols, keep the multilingual model and let the batch report count CJK characters

**Depends on:** [[TASK-002]]

## What was built

30 pages with a text layer from 29 PDFs (at least 3 different target symbols and 400 characters; seed 20261126; 459 PDFs visited), OCRed whole at 200 DPI with 5 recognition models plus one detector variant, against the text layer, NFKC. PP-OCRv6 medium recognizer with the small detector: words 92.6% of 7,235, numbers 98.2% of 1,190, µ 95.5% of 110, Greek 68.8% of 1,668, ± ≥ ≤ × all held, 0 CJK, 180 s; the wheel's small recognizer 92.4/98.0/70.9/42.1%, 70 s; en PP-OCRv5 mobile 87.9/98.0/91.8/41.5% and 0 of 2 ×; latin v5 and en v4 worse; the medium detector loses numbers (96.0%). Character lists from model metadata: v6 small and medium identical (18,708, 15,910 CJK); en v5 436, no en dash. Choice: PP-OCRv6 multilingual, small detector + medium recognizer via rec_model_path, batch report counts CJK; recorded in exploration.md section 12 and state.json decisions; TASK-004 and TASK-012 acceptance updated. Gates: make test 792 passed, 3 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- `.claude/work/2026-11-26_28_pdf-parsing-docling/exploration.md`
