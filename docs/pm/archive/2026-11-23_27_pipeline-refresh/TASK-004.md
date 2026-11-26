---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-004
status: done
kind: mechanism
title: "Make the real build join document_metadata"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-004 — Make the real build join document_metadata

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Defect 4 of the proposal: `_embed_pass` calls `build_ingested_doc(row, chunking=chunking, html_lookup=lookup)` at property_graph.py:307 without the metadata lookup. Only `ingest()` joins (ingest.py:213-228), and only tests call `ingest()`.

Move the miss-counting wrapper (ingest.py:216-221) into a named function both call. Use `mongo_metadata_lookup(client)` from harness/indexing/document_metadata.py. Let `build_property_graph_index` accept an injected `metadata_lookup` for tests, as it accepts `html_lookup`.

What the join cannot do (exploration 3.4): it reaches only documents the build builds, and it cannot clear a label (`_clean` drops None, property_graph.py:88). `propagate` stays a required step for label changes; TASK-018 says so in the docs. On a fresh build the join must reproduce doc_type on 55,930 documents, audience 20,386, site_topic 5,947, topic_hubs 49 (exploration 3.4). No fresh build is part of this item.

## Acceptance criteria

- [x] `tests/test_indexing_property_graph.py::test_build_joins_document_metadata` passes: the build over mongomock, with a document_metadata row that holds doc_type, upserts a :Document entity whose properties hold that doc_type
- [x] `grep -c 'counted_metadata_lookup' harness/indexing/ingest.py harness/indexing/property_graph.py` shows at least one use in each file: ingest() and the build share one function
- [x] `make test` passes and `make lint` passes, each run on its own line

## What was built

_embed_pass passes a counted mongo_metadata_lookup to build_ingested_doc, so a build stamps doc_type, audience, site_topic and topic_hubs; build_property_graph_index accepts metadata_lookup for tests. ingest() and the build share CountedMetadataLookup via counted_metadata_lookup (harness/indexing/ingest.py), which warns once with the miss count. Reached by python -m harness.indexing.build (not run: it writes to the live graph). Test: test_build_joins_document_metadata, which fails on the old call at property_graph.py:307. Gates: make test 755 passed, 2 skipped, 7 deselected; make lint All checks passed.

## Files it touched

- `harness/indexing/ingest.py`
- `harness/indexing/property_graph.py`
- `tests/test_indexing_property_graph.py`
