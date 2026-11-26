---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-013
status: done
kind: documentation
title: "Document the parser, the environment and the batch command"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-013 — Document the parser, the environment and the batch command

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Every command that writes says where. No path inside doctool in any public file.

## Acceptance criteria

- [x] A docs page says how to build the environment, run a batch, stop it, and read its report, and that Docling never enters .venv
- [x] `docs/RETRIEVAL.md` section 2 names the docling parser and says that nothing reaches the graph until row 21
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-002]], [[TASK-011]], [[TASK-012]]

## What was built

docs/PARSING_DOCLING.md: what the parser is (Docling 2.153.0, Heron pinned, PP-OCRv6 small detector + medium recognizer with the 30-page numbers, PaddleOCR-VL tables), the options hash, why Docling never enters .venv (make parse-env / make test-parse, what setup_parse_env.sh checks), how to rank, cut a list, parse (every option with its default), where each command writes (folders, failures.jsonl, batch_logs, the Mongo row only with --write-mongo), how to stop (<root>/STOP), how to read the report, the four post-processing rules with their reasons, and the files. docs/RETRIEVAL.md section 2's collection table gains the docling row: files only, nothing reaches the graph until row 21. README links the page. No doctool path in any new public file (grep). Gates: make test 840 passed, 3 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- [[PARSING_DOCLING]] — `docs/PARSING_DOCLING.md`
- [[RETRIEVAL]] — `docs/RETRIEVAL.md`
- `README.md`
