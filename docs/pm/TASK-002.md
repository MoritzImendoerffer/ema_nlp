---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-002
status: todo
kind: mechanism
title: "Select one row per URL: the first matching preference entry, then the newest parsed_at"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-002 — Select one row per URL: the first matching preference entry, then the newest parsed_at

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Today `iter_source_rows` (harness/indexing/ingest.py:159-196) reads `find({'error': ''}).sort('url', 1)` and keeps the first row per URL (line 182). The sort makes the rows of one URL adjacent (index url_idx), so selection groups consecutive rows; no second query.

Keep the signature `iter_source_rows(scope, *, client)` (callers: `_embed_pass` and `_links_pass` in property_graph.py, `ingest()`). Add `iter_source_groups(scope, *, client, preference=None)` yielding a small dataclass with `selected` and `old_rule`. `old_rule` is the first clean row the cursor yields for the URL: the rule before this change. TASK-006 and TASK-012 need it, because the proposal says that a graph document without the three values 'counts as built from the row that the old rule would have picked'.

Content type to preference key: 'pdf' in content_type gives 'application/pdf', 'html' gives 'text/html' (the same test as ingest.py:184-186). Store values today are exactly 'application/pdf' and 'text/html'.

Ties on parsed_at: the larger `_id` wins. A row without parsed_at counts as the oldest. `scope.limit` counts URLs, as today. Decision F: a URL whose rows match no entry falls back to its newest clean row; log one warning per URL and a total at the end of the pass.

## Acceptance criteria

- [ ] `tests/test_indexing_ingest.py::test_preferred_parser_row_wins` passes: rows (u, pymupdf4llm, legacy) and (u, pymupdf4llm, 1.27.2.3) inserted in both orders, the legacy row is yielded both times
- [ ] `tests/test_indexing_ingest.py::test_newest_row_of_one_parser_wins` passes: (u, trafilatura, legacy, parsed_at 2026-05-27) and (u, trafilatura, 2.0.0, parsed_at 2026-11-25), the 2.0.0 row is yielded
- [ ] `tests/test_indexing_ingest.py::test_unlisted_parser_falls_back_to_newest` passes: a URL with only llamahub_pdf_PDFReader rows yields the newest one, a warning is logged and the fallback count is 1
- [ ] `tests/test_indexing_ingest.py::test_old_rule_row_is_the_first_row_of_the_cursor` passes: iter_source_groups yields the selected row and the first clean row the cursor gave for the URL
- [ ] The 7 tests that tests/test_indexing_ingest.py holds today pass unchanged
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-001]]

## Files it touched

- `harness/indexing/ingest.py`
- `tests/test_indexing_ingest.py`
