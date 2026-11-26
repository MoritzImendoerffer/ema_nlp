# Implementation plan: PDF parsing with Docling and PaddleOCR models (row 17)

| | |
|---|---|
| Work unit | `2026-11-26_28_pdf-parsing-docling` |
| Proposal | [`docs/next/pdf_parsing_docling.md`](../../../docs/next/pdf_parsing_docling.md) at `ea628e2` |
| Exploration | [`exploration.md`](exploration.md) |
| Tasks | [`state.json`](state.json): 17 tasks |
| Planned | 2026-11-26, by Claude (Opus 5.5) |

## What is built

A parser named `docling` that runs only in its own environment: Docling 2.153.0, Heron at a
pinned revision, English PP-OCRv5 recognition through RapidOCR, and PaddleOCR-VL-1.6 as the
table stage, registered in code. Four post-processing rules run on the stored JSON in plain
Python: tables over pages, footnotes in tables, the model's markup, and title and reference
from the page header. A writer stores three files per PDF with a staged move. A ranking
script orders the PDFs by complex tables. A batch command parses a ranked list, and a report
script measures a batch. Batch 0 parses 270 PDFs (files only), and its page goes to
`docs/eval/`.

## How the parser stays out of the retrieval environment

- **Separate environment.** `make parse-env` builds `config.DOCLING_ENV`
  (`~/.local/share/ema_nlp/envs/docling`) with pinned versions. This repository is installed
  there with `--no-deps`. `.venv` is never touched: TASK-002 checks that torch stays at 2.10.0
  there and that `import docling` fails.
- **Split of the code.** The modules that import Docling are the parser, the table stage and
  the batch command. No module of `harness/` and nothing on the app's or the runner's path
  imports them. The store, the post-processing rules, the ranking and the report work on
  JSON and run in `.venv`, so the gate tests them.
- **Two test targets.** `make test` stays the gate and deselects the tests marked `parse`.
  `make test-parse` runs those in the parse environment and is reported, not a gate. Without
  Docling, the parser returns `missing_extra`.

## Order

1. The stored shape (TASK-001), then the environment (002), the table stage (003) and the
   parser (004).
2. The four post-processing rules (005 to 008). They need only stored JSON, so they can go in
   parallel with 002 to 004.
3. The writer (009), the ranking (010), the batch command (011) and the report (012), then
   the docs (013).
4. Batch 0's note (014, a checkpoint pre-answered by the owner's yes inside its envelope),
   the run (015), its page (016), and the report to the owner (017).

Critical path: 001 → 002 → 003 → 004 → 011 → 014 → 015 → 016 → 017.

## Choices the plan made (overrulable)

- **Docling 2.153.0**, by the exploration, as the proposal assigns.
- **English OCR** through RapidOCR's enum parameters (PP-OCRv5 mobile English recognition).
- **The environment** lives outside the repository and outside the sync.
- **The 70 random documents** are drawn from documents of at most 200 pages, so a few test the
  page ranges.
- **The ranking rule** is the proposal's own: 16,633 documents score above 0.
- **No `onnxruntime-gpu`** in batch 0: OCR touches 2.7% of pages.
- **Batch 0 writes files only**, plain JSON under `config.PARSED_ROOT`, and reports the gzip
  size. Mongo rows wait for an answer (open).

## What could go wrong

| Risk | Guard |
|---|---|
| An install moves the embedding model's torch | the separate environment; TASK-002 checks `.venv` |
| OCR in Chinese | the enum parameters; a test asserts no CJK character |
| A model download during a batch | the setup script prefetches and hashes every model |
| The join is slow on long tables | a single pass; a test with a 200-part table |
| Batch 0 exceeds 12 GPU hours | a 3-document rate measurement first; the batch is cut to fit |
| The GPU wedges under load | the 250 W cap and the pauses; the batch resumes from existing folders |

## What is not attempted

- No chunker and no change to the graph or the preference file: that is row 21.
- No batch after batch 0.
- No `doc.html`, `sidecar.json` or element ids.
- No second table model, and no PaddleOCR library.
