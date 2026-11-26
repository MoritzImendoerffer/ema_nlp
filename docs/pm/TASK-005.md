---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-005
status: todo
kind: mechanism
title: "Post-processing rule 1: join a table that runs over pages"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-005 — Post-processing rule 1: join a table that runs over pages

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

doctool's join is the example (`transforms.py:132-260`): adjacent in reading order, consecutive pages, same label, same `num_cols`, no caption on the continuation, repeated header dropped. Its loop rebuilds all elements for each join (`transforms.py:153-160`); this one walks once. Fixtures are small hand-made JSON files in Docling's format, cut from the exploration's real outputs (`$EMA_RESULTS_DIR/2026-11-26_row17_explore/probe_b/timed/`).

## Acceptance criteria

- [ ] `tests/test_docling_post.py::test_split_table_is_joined` passes: a stored document with one table on page 1 and its continuation on page 2 (same column count, adjacent in reading order) becomes one table with two provenance entries, pages 1 and 2
- [ ] `::test_repeated_header_is_dropped`, `::test_different_columns_are_not_joined` and `::test_join_is_linear` pass; the last joins a 200-part table without rebuilding the element list per part
- [ ] The rule works on the JSON dict of `doc.raw.json`, with no Docling import, and never changes the input
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-001]]

## Files it touched

- `corpus/parsers/docling_post.py`
- `tests/test_docling_post.py`
- `tests/fixtures/docling/`
