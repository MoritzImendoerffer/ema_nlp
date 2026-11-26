---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-003
status: todo
kind: mechanism
title: "Write the PaddleOCR-VL table stage and register it in code"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-003 — Write the PaddleOCR-VL table stage and register it in code

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Written here; doctool's `src/dw/parsers/paddleocr_vl_stage.py:54-183` is the example (exploration section 3). The model repository's configuration turns the generation cache off, which made one table 7 to 20 times slower in doctool: set `use_cache=True` on every generate call. Registration in code works in Docling 2.153.0 (exploration section 4); no entry point.

## Acceptance criteria

- [ ] `corpus/parsers/paddleocr_vl_table.py` defines the options class (kind `ema_paddleocr_vl`), the model class on `BaseTableStructureModel`, and `register()`, which calls `get_table_structure_factory(allow_external_plugins=True).register(...)`
- [ ] The model is `PaddlePaddle/PaddleOCR-VL-1.6` at revision `c5630abae1d940eafe0697512a0325494b02ab42`, bf16 on CUDA, greedy, `max_new_tokens=8192`, `use_cache=True`
- [ ] `make test-parse` passes `tests/test_docling_parse_env.py::test_table_stage_reads_a_table` (marked `parse` and `gpu`): a synthetic one-page PDF with a 3x3 table gives one table with 9 cells
- [ ] In .venv the module is not imported by any test of the gate
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-002]]

## Files it touched

- `corpus/parsers/paddleocr_vl_table.py`
- `tests/test_docling_parse_env.py`
