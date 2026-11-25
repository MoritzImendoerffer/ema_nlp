---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-005
status: todo
kind: mechanism
title: "Name the graph's writes and deletes in one module, with an in-memory double that models deletion"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-005 — Name the graph's writes and deletes in one module, with an in-memory double that models deletion

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Why: exploration finding 7. `_FakeStore` and `_RecordingStore` (tests/test_indexing_property_graph.py:98-162) record a query and return []. A test of 'no chunk of the first build remains' passes on them whatever the code does (rule 10 of docs/PLANNING_WORKFLOW.md). So the build talks to named operations, and the test double implements those operations on dicts. The Cypher itself is run on a real Neo4j in TASK-013.

Cypher to use (exploration 5.1, from EXPLAIN in a read session): `MATCH (d:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE c` plans as NodeIndexSeek on ema_document_id. Do not use `Neo4jPropertyGraphStore.delete` (llama_index/graph_stores/neo4j/neo4j_property_graph.py:738-770): its plan is AllNodesScan over 7.5 million nodes on each call. DETACH removes the PARENT_OF edges; the :Document node keeps LINKS_TO, category, tree_* and topic_hubs.

`CALL { ... } IN TRANSACTIONS OF n ROWS` needs an autocommit transaction, which `structured_query` gives (verified for `_delete_links`, property_graph.py:352-364). Batch sizes are parameters; TASK-014 fixes them from the measurement.

document_states: `MATCH (d:Document) RETURN d.id, d.parser, d.parser_version, d.text_sha256, EXISTS { (d)-[:HAS_CHUNK]->() }` (79,882 rows live). stamp_parse_identity: UNWIND of {id, parser, parser_version, text_sha256} rows, one SET per document.

## Acceptance criteria

- [ ] harness/indexing/graph_ops.py defines a class with the methods upsert, document_states, delete_document_chunks, stamp_parse_identity, delete_documents and reset_corpus, each sending Cypher through `store.structured_query` or the store's upsert methods
- [ ] `tests/test_graph_ops.py::test_cypher_shapes` passes: the chunk delete starts at `MATCH (d:Document {id:` and follows HAS_CHUNK; the reset names :Chunk and :Document and uses `IN TRANSACTIONS OF`; no query contains `MATCH (n) DETACH DELETE n` or `WHERE n.id IN`
- [ ] `tests/test_graph_ops.py::test_double_delete_removes_chunks_and_their_edges` passes on the in-memory double in tests/graph_double.py, which keeps nodes and edges by id
- [ ] `make test` passes and `make lint` passes, each run on its own line

## Files it touched

- `harness/indexing/graph_ops.py`
- `tests/graph_double.py`
- `tests/test_graph_ops.py`
