---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-006
status: done
kind: mechanism
title: "Resume by comparison: skip, stamp or replace each document"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-006 — Resume by comparison: skip, stamp or replace each document

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Replaces `_existing_doc_ids` (property_graph.py:233-238, used at :304), which skips every document that has a chunk.

Per selected row, with the graph's state from document_states:
- no :Document with chunks: build it (new);
- values present, text_sha256 equal, parser and version equal: skip;
- text_sha256 equal, parser or version different: stamp the two properties, touch no chunk (exploration 3.3: parse-html reproduces the legacy text on 200 of 200 sampled pages under a new version; without this rule the first run re-embeds 143,804 HTML leaves for nothing);
- text_sha256 different: replace;
- values absent (not backfilled): compare with the old-rule row from TASK-002. Same row: skip. Same hash: stamp. Other hash: replace.

Hash the row text before chunking, and chunk only to build or replace. Chunk first, delete afterwards (exploration 3.8: `chunk_document` returns [] when the splitter fails, chunking.py:66-78).

Delete the old chunks of the replaced documents inside `flush()`, just before the upsert, to keep the window without chunks short (one flush holds about 4,000 chunks). The three values ride on the entity, which `upsert_nodes` writes after the chunks (neo4j_property_graph.py:361-403). So a crash at any point leaves values that do not match, and the next build replaces again (exploration 5.2). State this invariant in the docstring.

`resume=False` (`--no-resume`) today re-MERGEs every document without deleting, which leaves stale chunks when a text got shorter. After this task it replaces every document: the plan's choice.

The comparison does not cover `chunk_sizes` or the embedding model (exploration 3.8). TASK-018 writes that down.

## Acceptance criteria

- [x] `tests/test_indexing_property_graph.py::test_changed_text_replaces_chunks` passes: a document of 6 leaves, then its row changed to a text of 2 leaves, built again: the double holds 2 leaves for it and no chunk id of the first build
- [x] `::test_unchanged_document_is_skipped` passes: the second build embeds nothing
- [x] `::test_equal_text_new_version_stamps_only` passes: rows (u, trafilatura, legacy) then (u, trafilatura, 2.0.0) with equal text: nothing is embedded and the :Document's parser_version becomes 2.0.0
- [x] `::test_text_without_chunks_keeps_old_chunks` passes: a new text that chunks to nothing leaves the old chunks in place and is counted
- [x] `::test_unstamped_document_counts_as_old_rule_row` passes: a graph document without the three values whose selected row is its old-rule row embeds nothing
- [x] `::test_failed_upsert_is_replaced_again` passes: an upsert that raises after the delete leaves values that do not match the row, and the next build replaces the document
- [x] The pass ends with one log line that counts new, replaced, stamped, skipped and fallback documents
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-002]], [[TASK-003]], [[TASK-004]], [[TASK-005]]

## What was built

_embed_pass (harness/indexing/property_graph.py) now takes a CorpusGraph, loads document_states once, and decides per selected row with _decide: new, skip, stamp (equal text hash, other parser or version: two properties set, no chunk touched) or replace (chunk first; the old chunks are deleted inside flush, after embedding and just before the upsert). A document without the three values is compared with its old-rule row. resume=False replaces every document. Returns EmbedPassStats and logs new, replaced, stamped, skipped, replace-without-chunks and preference fallbacks. _existing_doc_ids is removed. Reached by python -m harness.indexing.build through build_property_graph_index (not run live: it writes; TASK-013 runs it on a throwaway Neo4j). 10 new tests on tests/graph_double.py. Gates: make test 771 passed, 2 skipped, 7 deselected; make lint All checks passed.

## Files it touched

- `harness/indexing/property_graph.py`
- `tests/test_indexing_property_graph.py`
