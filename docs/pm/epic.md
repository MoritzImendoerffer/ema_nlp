---
type: pm-epic
epic: 2026-11-26_28_pdf-parsing-docling
status: in-progress
opened: 2026-11-26
tags: [pm/epic]
---

# PDF parsing with Docling and PaddleOCR models: the parser, its post-processing, batch 0

Written by Claude (Opus 5.5) during `/plan` on 2026-11-26. This note is hand-written;
`scripts/pm_notes.py` never changes it.

**Backlog row 17**, top of `Now` in [`BACKLOG.md`](../../../../BACKLOG.md) ·
proposal: [`docs/next/pdf_parsing_docling.md`](../../../next/pdf_parsing_docling.md) ·
plan: `.claude/work/2026-11-26_28_pdf-parsing-docling/implementation-plan.md` ·
board: [[_Board]]

## Why this epic

The owner decided on 2026-11-25 that the PDFs are parsed with Docling and PaddleOCR models.
A chunk today knows no page and no position. Tables are flattened. The parse records no
element.

This epic builds the parser in its own environment, keeping Docling out of the retrieval
environment. It adds four post-processing rules and a batch command, and parses batch 0:
270 PDFs, files only, inside the owner's yes of 2026-11-25. Nothing reaches the graph here;
that is row 21.
