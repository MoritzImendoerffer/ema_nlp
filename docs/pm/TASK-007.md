---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-007
status: todo
kind: mechanism
title: "Add prune: delete documents whose URL has no clean row, whatever the scope"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-007 — Add prune: delete documents whose URL has no clean row, whatever the scope

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Decision B (docs/pm/decisions/2026-11-25_removed-urls.md): kept by default, deleted with prune.

Compare the graph with ALL clean URLs: `distinct('url', {'error': ''})` over parsed_documents, restricted to pdf and html content types. Never with the scope: `--prune --limit 200` would otherwise remove 79,682 documents (exploration 3.7).

Deleting a :Document deletes its chunks and its LINKS_TO edges. `tree_parent_id` and `topic_hubs` on other documents then describe edges that are gone until the steps `tree` and `subgraphs` run again; log that hint after a prune that deleted anything.

Live: 0 graph documents lack a clean row today (exploration 4.3), so a prune would delete nothing.

## Acceptance criteria

- [ ] `tests/test_indexing_property_graph.py::test_prune_deletes_document_without_clean_row` passes
- [ ] `::test_prune_ignores_scope_limit` passes: with scope.limit = 1, a document that has a clean row outside the first URL stays
- [ ] `::test_prune_off_by_default` passes
- [ ] Prune logs the count and the first 20 URLs before it deletes anything
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]]

## Files it touched

- `harness/indexing/property_graph.py`
- `tests/test_indexing_property_graph.py`
