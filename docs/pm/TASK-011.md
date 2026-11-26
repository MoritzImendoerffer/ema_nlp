---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-011
status: done
kind: wiring
title: "Write the batch command and wire the parser, the post-processing and the writer into it"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-011 — Write the batch command and wire the parser, the post-processing and the writer into it

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Proposal section 'The batch command'. The nulojix RMP summary (12.4 million characters) fails on every graph build (row 10's measurement page); the command must list such a document and go on. Runs only in the parse environment.

## Acceptance criteria

- [x] The command takes a ranked list and a page budget, decompresses a gzip body, skips a document whose folder exists for these options, and replaces its worker process after a set number of documents
- [x] A PDF above a set number of pages is parsed in page ranges and joined; a failed or partial document is listed and the batch goes on
- [x] It pauses on a schedule (`--pause-every-docs`, `--pause-seconds`) and stops between documents when a stop file exists
- [x] `tests/test_parse_pdfs_docling.py` passes in the gate with a stand-in parser: skip of an existing folder, budget, failure listed, stop file honoured
- [x] `make test-parse` runs the command on 2 small PDFs end to end
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-004]], [[TASK-009]], [[TASK-010]]

## What was built

scripts/parse_pdfs_docling.py (CLI) runs the loop in corpus/parsers/docling_batch.py (a module, so a spawned worker can import process_one by name). It reads a JSONL list (url, cache_path, optional pages/group), decompresses gzip bodies, skips a document whose docling@<hash> folder holds run.json, takes documents in order until the next would exceed --budget-pages, parses each in a ProcessPoolExecutor worker (spawn, max_tasks_per_child=--docs-per-worker, default 50; --workers default 1), post-processes and writes the three files; a failed/partial document or a dead worker is listed in failures.jsonl and the batch goes on (a broken pool is replaced). --pause-every-docs/--pause-seconds (default 20 docs / 60 s) pause with no document in a worker; <root>/STOP (or --stop-file) stops between documents. A per-batch log JSONL goes to <root>/batch_logs/. It prints the GPU power limit at the start. --write-mongo is off by default. corpus/parsers/docling_pdf.py gains page ranges (--range-pages, default 100: Docling's page_range per part, joined by DoclingDocument.concatenate; parts keep their page numbers, checked on the 8-page fixture), package_versions() and device(). Tests: tests/test_parse_pdfs_docling.py 7 passed in the gate with a stand-in parser (skip, budget, failure listed, unreadable cache, stop file, pauses, ranges); make test-parse 11 passed incl. the command as a process on 2 PDFs (gzip body; 8 pages in 2 ranges of 5; a new worker per document; 9 pages, 0 failures). Gates: make test 835 passed, 3 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- `scripts/parse_pdfs_docling.py`
- `corpus/parsers/docling_batch.py`
- `corpus/parsers/docling_pdf.py`
- `tests/test_parse_pdfs_docling.py`
- `tests/test_docling_parse_env.py`
