---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-005
status: done
kind: mechanism
title: "Post-processing rule 1: join a table that runs over pages"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-005 — Post-processing rule 1: join a table that runs over pages

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

doctool's join is the example (`transforms.py:132-260`): adjacent in reading order, consecutive pages, same label, same `num_cols`, no caption on the continuation, repeated header dropped. Its loop rebuilds all elements for each join (`transforms.py:153-160`); this one walks once. Fixtures are small hand-made JSON files in Docling's format, cut from the exploration's real outputs (`$EMA_RESULTS_DIR/2026-11-26_row17_explore/probe_b/timed/`).

## Acceptance criteria

- [x] `tests/test_docling_post.py::test_split_table_is_joined` passes: a stored document with one table on page 1 and its continuation on page 2 (same column count, adjacent in reading order) becomes one table with two provenance entries, pages 1 and 2
- [x] `::test_repeated_header_is_dropped`, `::test_different_columns_are_not_joined` and `::test_join_is_linear` pass; the last joins a 200-part table without rebuilding the element list per part
- [x] The rule works on the JSON dict of `doc.raw.json`, with no Docling import, and never changes the input
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-001]]

## What was built

corpus/parsers/docling_post.py: post_process(raw) -> (doc, counts) on a deep copy; rule 1 join_tables_over_pages: one pass over the body's reading order; part B joins table A when only furniture items (page headers and footers), A's captions and footnotes, and pictures on A's last page (the logo on EMA first pages) lie between, B starts on the next page, same label and column count, no caption on B; repeated header rows dropped; provenance, footnotes, references and children carried over; parts removed and every #/tables/N renumbered once; grids rebuilt. Real fixture tests/fixtures/docling/trepulmix_procedural_steps.raw.json (61 KB, Docling 2.153.0 export): 4 tables -> 1 table of 16 rows on pages 1-4 with its 3 footnotes. 7 tests in tests/test_docling_post.py (incl. a 200-part table joined in one pass under 5 s, input unchanged, text between parts ends the table). make test-parse: 7 passed incl. the joined document loading as a DoclingDocument and rendering to Markdown. Gates: make test 802 passed, 3 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- `corpus/parsers/docling_post.py`
- `tests/test_docling_post.py`
- `tests/fixtures/docling/`
