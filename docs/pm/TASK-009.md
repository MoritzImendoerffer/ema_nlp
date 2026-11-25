---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-009
status: todo
kind: mechanism
title: "Add a PDF parser that reads bytes with the installed pymupdf4llm"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-009 — Add a PDF parser that reads bytes with the installed pymupdf4llm

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Defect 1 of the proposal: the module parses no PDF; it unpickles the scraper's `parsed_pdf.pkl` (corpus/parsers/pymupdf4llm.py:100) and fails with `pickle_load_failed: No module named 'parsers'` outside the scraper's path.

Installed library, read on 2026-11-25 (.venv/lib/python3.13/site-packages/pymupdf4llm/__init__.py): pymupdf4llm 1.27.2.3, pymupdf 1.27.2.3, pymupdf-layout 1.27.2.3. `to_markdown(*args, **kwargs)` goes to `_layout_to_markdown` when `_use_layout` is True, and it is True on import here. `_layout_to_markdown(doc, *, ..., footer=True, header=True, use_ocr=True, ...)`: the three options are keyword-only. Open bytes with `pymupdf.open(stream=raw, filetype='pdf')`.

Decision E (docs/pm/decisions/2026-11-25_pdf-ocr.md): pass use_ocr=True, header=True, footer=True explicitly; record them, layout mode and the three versions in meta. OCR uses /usr/bin/tesseract, outside .venv: the tests must not compare OCR text, only length, error and stability.

A body that starts with the bytes 1f 8b is decompressed with gzip first (exploration: one 'bad magic' entry starts with 1f8b0800, Content-Encoding gzip). Whether the 6,760 such PDFs are parsed is row 11's data task.

The library prints to standard output ('=== Document parser messages ===', 'OCR on page.number=0/1'). Do not assert on stdout.

The fixture took 1.56 s and 1.85 s on the CPU and gave 11,906 characters with the same SHA-256 both times (exploration 6.2).

Name: parser `pymupdf4llm`, version = the installed library version. Keep the pickle reader in the module under another class name and keep `_cli` on it: switching the CLI waits for decision G (TASK-010).

## Acceptance criteria

- [ ] `tests/test_parsers_pymupdf4llm.py::test_pdf_parser_reads_bytes` passes: the bytes of tests/fixtures/fixture_pdf_0.pdf give more than 1,000 characters of text, error '', and the module `parsers` is not imported
- [ ] `::test_gzip_body_is_decompressed` passes: `gzip.compress(fixture)` gives the same text as the plain bytes
- [ ] `::test_meta_records_options` passes: meta holds use_ocr True, header True, footer True, layout True, and the versions of pymupdf4llm, pymupdf and pymupdf-layout
- [ ] `::test_not_a_pdf_returns_error` passes: b'hello' gives empty text and an error that starts with 'pdf_open_failed'
- [ ] The 13 tests that tests/test_parsers_pymupdf4llm.py holds today pass: the pickle reader stays until TASK-010
- [ ] `make test` passes and `make lint` passes, each run on its own line

## Files it touched

- `corpus/parsers/pymupdf4llm.py`
- `tests/test_parsers_pymupdf4llm.py`
