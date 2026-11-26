---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-004
status: done
kind: mechanism
title: "Write the docling parser on the Parser protocol"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-004 — Write the docling parser on the Parser protocol

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

`corpus/parsers/base.py:40-58` is the protocol; `llamahub_pdf.py:123` is the example of `missing_extra`. The options and their hash go into run.json. Exploration section 5: `lang=['en']` alone loads the multilingual PP-OCRv6 model, and the first look's 'authorisation 木' comes back.

## Acceptance criteria

- [x] `tests/test_parsers_docling_pdf.py::test_missing_extra_in_retrieval_env` passes in the gate: without Docling, `parse()` returns a document whose error starts with `missing_extra`
- [x] The converter uses Heron pinned through `LayoutObjectDetectionOptions.from_preset('layout_heron_default')`, RapidOCR PP-OCRv6 with `model_size='small'` and `rec_model_path` set to the medium recognizer (`multi_PP-OCRv6_rec_medium.onnx`, SHA-256 from rapidocr 3.10.0's default_models.yaml), the table stage of TASK-003, and `allow_external_plugins=True`; `prefetch()` downloads and checks the medium recognizer and builds the converter once, so every model is on disk before a batch
- [x] A status other than SUCCESS (PARTIAL_SUCCESS included) is returned as an error; `parse()` never raises
- [x] `make test-parse` passes `::test_parser_on_fixture_pdf`: `tests/fixtures/fixture_pdf_0.pdf` gives SUCCESS and a page count
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-001]], [[TASK-003]], [[TASK-018]]

## What was built

corpus/parsers/docling_pdf.py: OPTIONS (Heron at 8f39ad3c via LayoutObjectDetectionOptions.from_preset; RapidOCR onnxruntime, model_size small, rec_model_path = PP-OCRv6 medium recognizer; PaddleOCR-VL stage c5630abae1d9 at 200 DPI) with OPTIONS_HASH 6eceaf4e; fetch_rec_model() downloads the medium recognizer from RapidOCR's host and checks SHA-256 eef44482…; build_converter() (lru-cached, registers the table stage); prefetch(); convert_pdf(raw) never raises, decompresses gzip, treats any status but SUCCESS as an error, returns the document dict, Markdown and counts; DoclingPdfParser on the Parser protocol (version <docling version>+<options hash>), missing_extra without Docling. scripts/setup_parse_env.sh runs the prefetch. Gate: tests/test_parsers_docling_pdf.py (3 passed: missing_extra in .venv, protocol and options). make test-parse: 6 passed (fixture_pdf_0.pdf SUCCESS with text; the 3x3 table fixture gives 1 table of 9 cells, gzip gives the same Markdown; the converter's OCR options carry the medium recognizer path and model_size small). Gates: make test 795 passed, 3 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- `corpus/parsers/docling_pdf.py`
- `tests/test_parsers_docling_pdf.py`
- `tests/test_docling_parse_env.py`
