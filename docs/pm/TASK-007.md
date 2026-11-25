---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-007
status: done
kind: mechanism
title: "Add prune: delete documents whose URL has no clean row, whatever the scope"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-007 — Add prune: delete documents whose URL has no clean row, whatever the scope

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Decision B (docs/pm/decisions/2026-11-25_removed-urls.md): kept by default, deleted with prune.

Compare the graph with ALL clean URLs: `distinct('url', {'error': ''})` over parsed_documents, restricted to pdf and html content types. Never with the scope: `--prune --limit 200` would otherwise remove 79,682 documents (exploration 3.7).

Deleting a :Document deletes its chunks and its LINKS_TO edges. `tree_parent_id` and `topic_hubs` on other documents then describe edges that are gone until the steps `tree` and `subgraphs` run again; log that hint after a prune that deleted anything.

Live: 0 graph documents lack a clean row today (exploration 4.3), so a prune would delete nothing.

## Acceptance criteria

- [x] `tests/test_indexing_property_graph.py::test_prune_deletes_document_without_clean_row` passes
- [x] `::test_prune_ignores_scope_limit` passes: with scope.limit = 1, a document that has a clean row outside the first URL stays
- [x] `::test_prune_off_by_default` passes
- [x] Prune logs the count and the first 20 URLs before it deletes anything
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]]

## What was built

prune_documents(graph, client) in harness/indexing/property_graph.py compares every :Document's source_url with clean_source_urls (all clean pdf/html rows of parsed_documents, never the scope), logs the count and the first 20 URLs, then deletes the documents with their chunks and LINKS_TO edges and logs the tree/subgraphs hint. build_property_graph_index(prune=False) calls it when asked (decision B). 4 tests. Read-only on the live stores, 2026-11-25: 79,882 graph documents (79,882 with chunks, 0 stamped), 80,078 clean URLs, 0 prune candidates (document_states took 7.3 s). The --prune flag is wired in TASK-011. Gates: make test 775 passed, 2 skipped, 7 deselected; make lint All checks passed.

## Files it touched

- `harness/indexing/property_graph.py`
- `tests/test_indexing_property_graph.py`
