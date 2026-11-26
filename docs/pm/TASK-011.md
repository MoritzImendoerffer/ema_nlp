---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-011
status: todo
kind: wiring
title: "Write the batch command and wire the parser, the post-processing and the writer into it"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-011 — Write the batch command and wire the parser, the post-processing and the writer into it

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Proposal section 'The batch command'. The nulojix RMP summary (12.4 million characters) fails on every graph build (row 10's measurement page); the command must list such a document and go on. Runs only in the parse environment.

## Acceptance criteria

- [ ] The command takes a ranked list and a page budget, decompresses a gzip body, skips a document whose folder exists for these options, and replaces its worker process after a set number of documents
- [ ] A PDF above a set number of pages is parsed in page ranges and joined; a failed or partial document is listed and the batch goes on
- [ ] It pauses on a schedule (`--pause-every-docs`, `--pause-seconds`) and stops between documents when a stop file exists
- [ ] `tests/test_parse_pdfs_docling.py` passes in the gate with a stand-in parser: skip of an existing folder, budget, failure listed, stop file honoured
- [ ] `make test-parse` runs the command on 2 small PDFs end to end
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-004]], [[TASK-009]], [[TASK-010]]

## Files it touched

- `scripts/parse_pdfs_docling.py`
- `tests/test_parse_pdfs_docling.py`
