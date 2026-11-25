---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-003
status: todo
kind: contract
title: "Put parser, parser_version and text_sha256 on the :Document node"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-003 — Put parser, parser_version and text_sha256 on the :Document node

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

`build_ingested_doc` (ingest.py:108-116) already puts `parser` in `metadata`; add `parser_version` and `text_sha256` there, and write all three in `_entity_for` (property_graph.py:172-203). Hash the row's `text` exactly as stored (`pd.get('text', '') or ''`), UTF-8, 64 hex characters.

Do not add them to `base_meta` (ingest.py:128-133), which goes into the chunk nodes: the chunk ids and texts must stay. The exploration (section 4.3) checked 80 of 80 documents: today's rows rebuild exactly the chunk ids in the graph.

Stored shape: the 79,882 existing :Document nodes do not have the three properties until TASK-016. `MATCH (d:Document) RETURN count(d.parser), count(d.parser_version), count(d.text_sha256)` gave 0, 0, 0 on 2026-11-23.

## Acceptance criteria

- [ ] `tests/test_indexing_property_graph.py::test_entity_carries_parse_identity` passes: `_entity_for(doc).properties` holds parser, parser_version, and text_sha256 equal to `hashlib.sha256(row['text'].encode('utf-8')).hexdigest()`
- [ ] `tests/test_indexing_property_graph.py::test_parse_identity_leaves_chunks_unchanged` passes: the chunk ids, texts and leaf flags of build_ingested_doc equal those of chunk_document for the same text
- [ ] `make test` passes and `make lint` passes, each run on its own line

## Files it touched

- `harness/indexing/ingest.py`
- `harness/indexing/property_graph.py`
- `tests/test_indexing_property_graph.py`
