---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-018
status: todo
kind: measurement
title: "Measure the OCR recognition models on pages with a known answer, and choose one"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-018 — Measure the OCR recognition models on pages with a known answer, and choose one

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Required by the lead session's review of 2026-11-26 before TASK-004 fixes the model. The exploration's switch rested on one wrong character in one document, and 'no CJK character' is a weak test: a model that cannot write CJK passes it by construction. The larger risk is µg read as ug or mg, which changes a dose. OCR touches 30,614 pages in 5,503 documents (exploration section 6). CPU work of minutes; no approval needed.

## Acceptance criteria

- [ ] About 30 pages with a text layer from about 10 cached PDFs, chosen so that they hold µ, ±, ≥, ≤, °, × and Greek letters; the page list and the rule written down
- [ ] Each recognition model OCRs the whole page image: the multilingual PP-OCRv6 small model, en_PP-OCRv5_rec_mobile, and any other English or Latin recognition model that rapidocr 3.10.0 offers
- [ ] Against the text layer: the share of words, of numbers and of each symbol held, and the CJK characters returned, per model, each with n
- [ ] The choice and the numbers go into an addendum of exploration.md and into the plan's choices; if the English model loses symbols, keep the multilingual model and let the batch report count CJK characters

**Depends on:** [[TASK-002]]

## Files it touched

- `.claude/work/2026-11-26_28_pdf-parsing-docling/exploration.md`
