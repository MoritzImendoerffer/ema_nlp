---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-003
status: done
kind: mechanism
title: "Write the PaddleOCR-VL table stage and register it in code"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-003 — Write the PaddleOCR-VL table stage and register it in code

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Written here; doctool's `src/dw/parsers/paddleocr_vl_stage.py:54-183` is the example (exploration section 3). The model repository's configuration turns the generation cache off, which made one table 7 to 20 times slower in doctool: set `use_cache=True` on every generate call. Registration in code works in Docling 2.153.0 (exploration section 4); no entry point. Written fresh in this repository's style; no public file (code comment, docs page, README) points at a path inside doctool (lead session's review of 2026-11-26).

## Acceptance criteria

- [x] `corpus/parsers/paddleocr_vl_table.py` defines the options class (kind `ema_paddleocr_vl`), the model class on `BaseTableStructureModel`, and `register()`, which calls `get_table_structure_factory(allow_external_plugins=True).register(...)`
- [x] The model is `PaddlePaddle/PaddleOCR-VL-1.6` at revision `c5630abae1d940eafe0697512a0325494b02ab42`, bf16 on CUDA, greedy, `max_new_tokens=8192`, `use_cache=True`
- [x] `make test-parse` passes `tests/test_docling_parse_env.py::test_table_stage_reads_a_table` (marked `parse` and `gpu`): a synthetic one-page PDF with a 3x3 table gives one table with 9 cells
- [x] In .venv the module is not imported by any test of the gate
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-002]]

## What was built

corpus/parsers/paddleocr_vl_table.py, written fresh: PaddleOcrVlTableOptions (kind ema_paddleocr_vl), PaddleOcrVlTableModel on BaseTableStructureModel (checked against Docling 2.153.0: abstract get_options_type and predict_tables(conv_res, pages)), PaddleOCR-VL-1.6 at c5630abae1d940eafe0697512a0325494b02ab42 via download_hf_model, bf16 on CUDA, greedy, max_new_tokens 8192, use_cache=True, crops at 200 DPI; register() calls get_table_structure_factory(allow_external_plugins=True).register and is idempotent (registered_kind checked, ValueError on a duplicate caught). No public reference into doctool. Test tests/fixtures/docling/table_3x3.pdf (3,216 bytes, made with pymupdf); make test-parse: test_table_stage_reads_a_table passed (one 3x3 table with 'Age group', '12.5', 'twice daily'), 3 passed in 13.5 s on the GPU. Gates: make test 792 passed, 3 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- `corpus/parsers/paddleocr_vl_table.py`
- `tests/test_docling_parse_env.py`
