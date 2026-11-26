---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-009
status: done
kind: mechanism
title: "Write the writer: three files, a staged move, the failures list, the Markdown text and the Mongo row"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-009 — Write the writer: three files, a staged move, the failures list, the Markdown text and the Mongo row

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Whether batch 0 writes rows is open (state.json decisions); the default is files only, as the owner's yes says. The Markdown is rendered in the parse environment with docling-core from doc.json; the guard keeps the row under MongoDB's 16 MB (the largest legacy row holds 12.45 million characters).

## Acceptance criteria

- [x] `::test_failed_write_keeps_previous_folder` passes: a write that fails mid-way leaves the previous folder byte-identical
- [x] `::test_failure_is_listed` passes: a failed parse appends `{url, doc_id, error, sha256}` to `<root>/failures.jsonl` and writes no folder
- [x] `::test_mongo_row_shape` passes on mongomock: key `(url, 'docling', '<docling version>+<hash8>')`, `content_type` application/pdf, `meta` with doc id, relative folder, source hash and counts, a size guard below 16 MB
- [x] Writing the Mongo row is off unless `--write-mongo` is given
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-001]], [[TASK-005]], [[TASK-006]], [[TASK-007]], [[TASK-008]]

## What was built

corpus/parsers/docling_store.py gains the writer: write_parse(folder, raw, doc, run) writes doc.raw.json, doc.json and run.json into <folder>.tmp and swaps it in only when all three are written (previous folder renamed to .old, new moved in, .old deleted); a failure before the swap removes the staging folder and leaves the previous folder byte-identical. append_failure() appends {url, doc_id, sha256, error, at} to <root>/failures.jsonl and writes no folder. run_record() builds run.json (schema_version 1, doc id, url, source sha256, options and hash, versions, counts, seconds, device, created_at). mongo_row() builds the parsed_documents row (key url, docling, <docling version>+<hash8>; meta with doc id, relative folder, source hash, counts, text_truncated) with the text cut at 14 MiB of UTF-8, below MongoDB's 16 MB; the batch command writes it only with --write-mongo (lead session's review: files only in batch 0, decision F). 6 new tests (12 in tests/test_docling_store.py) incl. a failed write keeping the previous folder and the row written through write_parsed_document on mongomock. Gates: make test 820 passed, 3 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- `corpus/parsers/docling_store.py`
- `tests/test_docling_store.py`
