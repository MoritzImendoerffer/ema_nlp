---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-009
status: todo
kind: mechanism
title: "Write the writer: three files, a staged move, the failures list, the Markdown text and the Mongo row"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-009 — Write the writer: three files, a staged move, the failures list, the Markdown text and the Mongo row

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Whether batch 0 writes rows is open (state.json decisions); the default is files only, as the owner's yes says. The Markdown is rendered in the parse environment with docling-core from doc.json; the guard keeps the row under MongoDB's 16 MB (the largest legacy row holds 12.45 million characters).

## Acceptance criteria

- [ ] `::test_failed_write_keeps_previous_folder` passes: a write that fails mid-way leaves the previous folder byte-identical
- [ ] `::test_failure_is_listed` passes: a failed parse appends `{url, doc_id, error, sha256}` to `<root>/failures.jsonl` and writes no folder
- [ ] `::test_mongo_row_shape` passes on mongomock: key `(url, 'docling', '<docling version>+<hash8>')`, `content_type` application/pdf, `meta` with doc id, relative folder, source hash and counts, a size guard below 16 MB
- [ ] Writing the Mongo row is off unless `--write-mongo` is given
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-001]], [[TASK-005]], [[TASK-006]], [[TASK-007]], [[TASK-008]]

## Files it touched

- `corpus/parsers/docling_store.py`
- `tests/test_docling_store.py`
