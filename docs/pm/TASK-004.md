---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-004
status: todo
kind: mechanism
title: "Write the docling parser on the Parser protocol"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-004 — Write the docling parser on the Parser protocol

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

`corpus/parsers/base.py:40-58` is the protocol; `llamahub_pdf.py:123` is the example of `missing_extra`. The options and their hash go into run.json. Exploration section 5: `lang=['en']` alone loads the multilingual PP-OCRv6 model, and the first look's 'authorisation 木' comes back.

## Acceptance criteria

- [ ] `tests/test_parsers_docling_pdf.py::test_missing_extra_in_retrieval_env` passes in the gate: without Docling, `parse()` returns a document whose error starts with `missing_extra`
- [ ] The converter uses Heron pinned through `LayoutObjectDetectionOptions.from_preset('layout_heron_default')`, RapidOCR with `Rec.lang_type=LangRec.EN`, `Rec.ocr_version=OCRVersion.PPOCRV5`, `Rec.model_type=ModelType.MOBILE`, the table stage of TASK-003, and `allow_external_plugins=True`
- [ ] A status other than SUCCESS (PARTIAL_SUCCESS included) is returned as an error; `parse()` never raises
- [ ] `make test-parse` passes `::test_parser_on_fixture_pdf`: `tests/fixtures/fixture_pdf_0.pdf` gives SUCCESS, a page count, and no CJK character
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-001]], [[TASK-003]]

## Files it touched

- `corpus/parsers/docling_pdf.py`
- `tests/test_parsers_docling_pdf.py`
- `tests/test_docling_parse_env.py`
