---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-001
status: todo
kind: contract
title: "Give parser_preference.yaml a reader that understands name@version"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-001 — Give parser_preference.yaml a reader that understands name@version

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Decisions A and D (docs/pm/decisions/2026-11-25_pdf-parser-order.md, 2026-11-25_legacy-parser-name.md). The file becomes: application/pdf: [pymupdf4llm@legacy, pymupdf4llm]; text/html: [trafilatura]. An entry 'name' matches every version of that parser; 'name@version' matches that version only.

The header of the file says today (lines 3-9) that nothing reads it; replace it with what the reader does and a pointer to decision D. The file is authored data (CLAUDE.md rule 3): edited by hand here, read by code, written by no tool.

A reader existed once: `git show a70c38c:harness/embed_pg.py`, lines 86-122 (`load_parser_preference`). Do not restore its command-line override: the proposal does not ask for one (rule 1).

Keep the reader pure (path in, mapping out) so TASK-002 can test selection without a file.

## Acceptance criteria

- [ ] `tests/test_parser_preference.py::test_loads_shipped_file` passes: the shipped file loads as {'application/pdf': [('pymupdf4llm', 'legacy'), ('pymupdf4llm', None)], 'text/html': [('trafilatura', None)]}
- [ ] `tests/test_parser_preference.py::test_entry_with_version_matches_that_version_only` and `::test_entry_without_version_matches_every_version` pass
- [ ] `tests/test_parser_preference.py::test_malformed_file_raises` passes: a top-level list, an empty entry and 'a@' each raise ValueError
- [ ] `grep -c 'does NOT yet' harness/configs/parser_preference.yaml` prints 0
- [ ] `make test` passes and `make lint` passes, each run on its own line

## Files it touched

- `harness/configs/parser_preference.yaml`
- `harness/indexing/parser_preference.py`
- `tests/test_parser_preference.py`
