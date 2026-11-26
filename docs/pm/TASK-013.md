---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-013
status: todo
kind: documentation
title: "Document the parser, the environment and the batch command"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-013 — Document the parser, the environment and the batch command

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Every command that writes says where.

## Acceptance criteria

- [ ] A docs page says how to build the environment, run a batch, stop it, and read its report, and that Docling never enters .venv
- [ ] `docs/RETRIEVAL.md` section 2 names the docling parser and says that nothing reaches the graph until row 21
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-002]], [[TASK-011]], [[TASK-012]]

## Files it touched

- [[PARSING_DOCLING]] — `docs/PARSING_DOCLING.md`
- [[RETRIEVAL]] — `docs/RETRIEVAL.md`
- `README.md`
