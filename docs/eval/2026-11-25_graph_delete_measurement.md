# Deleting from the graph: measured on a throwaway Neo4j

**Date:** 2026-11-25 · **Written by:** Claude (Opus 5.5) · **Work unit:**
`2026-11-23_27_pipeline-refresh`, TASK-013 · **Backlog row:** 10

Work unit 27 adds the first code that deletes from the live graph: the replace step of a
refreshed document, `--prune`, and a batched `--reset` (`harness/indexing/graph_ops.py`).
The exploration (`.claude/work/2026-11-23_27_pipeline-refresh/exploration.md`, sections 5.1
and 5.3) left three questions that need a real Neo4j. This page answers them on a throwaway
instance with synthetic data. **The live graph was not touched.**

## Setup

| | |
|---|---|
| Instance | container `ema_neo4j_scratch`, started for this run and removed after it (`docker rm -f -v`) |
| Image | `neo4j:5.26`, image id `sha256:a5bf2ed9f12a…`, the same image as the live `ema_neo4j` (5.26.26) |
| Memory | `server.memory.heap.max_size` 2.00 GiB, `dbms.memory.transaction.total.max` 1.40 GiB, page cache 1.00 GiB, read back with `SHOW SETTINGS`: the live server's values |
| Ports | bolt on `127.0.0.1:7688`, http on `127.0.0.1:7475`; no named volume |
| Data | synthetic, made with plain Cypher (below). No GPU, no model, 0 paid calls |
| Load | the machine ran other sessions' work; load average about 14 during the runs |

```bash
docker run -d --name ema_neo4j_scratch -p 127.0.0.1:7688:7687 -p 127.0.0.1:7475:7474 \
  -e NEO4J_AUTH=neo4j/<scratch password> -e NEO4J_PLUGINS='["apoc"]' \
  -e NEO4J_server_memory_heap_max__size=2G -e NEO4J_server_memory_heap_initial__size=2G \
  -e NEO4J_server_memory_pagecache_size=1G -e NEO4J_dbms_memory_transaction_total_max=1.4g \
  neo4j:5.26
```

A synthetic document has `n` chunks: the first `p` are parents without an embedding, the rest
are leaves with a 1,024-float embedding written by `db.create.setNodeVectorProperty`, as the
build writes them. Each chunk has 2,000 characters of text, a `HAS_CHUNK` edge from its
document and, for a leaf, a `PARENT_OF` edge from a parent. The vector index
`ema_chunk_embedding` (1,024 dimensions, cosine) exists before the data is written, so every
write and delete maintains it.

```cypher
UNWIND range(0, $n - 1) AS i
CALL { WITH i
  MATCH (d:Document {id: $doc})
  CREATE (c:__Node__:Chunk {id: $doc + '-' + toString(i), doc_id: $doc, text: $text, is_leaf: i >= $parents})
  CREATE (d)-[:HAS_CHUNK]->(c)
  WITH c, i WHERE i >= $parents
  CALL db.create.setNodeVectorProperty(c, 'embedding', [x IN range(1, 1024) | rand()])
} IN TRANSACTIONS OF 2000 ROWS
```

## 1. Does a deleted chunk leave the vector index at once?

**Yes.** `tests/test_graph_ops_neo4j.py::test_deleted_chunk_leaves_the_vector_index_at_once`
builds a document through the real `_embed_pass`, takes one leaf's embedding, and queries
`CALL db.index.vector.queryNodes('ema_chunk_embedding', 50, $e)`. The leaf is in the result
before `MATCH (c:Chunk {id: $id}) DETACH DELETE c` and absent from the same query right
after the delete commits.

All 6 tests of that file passed against the scratch instance (13.1 s):

```bash
EMA_SCRATCH_NEO4J_URI=bolt://localhost:7688 EMA_SCRATCH_NEO4J_PASSWORD=<scratch password> \
  .venv/bin/python -m pytest -m integration tests/test_graph_ops_neo4j.py
```

They also show on Neo4j what the in-memory double shows: a replace leaves no chunk of the
first build and no chunk without a `HAS_CHUNK` edge; an unchanged second build embeds
nothing; prune deletes exactly the document whose URL lost its row; a reset with 7 rows per
batch deletes every `:Document` and `:Chunk` and keeps a `_Neodash_Dashboard` node.

## 2. Can one document's chunks be deleted in one transaction?

The biggest live document has 25,916 chunks (exploration, section 4.2).

| Run | Chunks (leaves) | Statement | Time | Outcome |
|---|---|---|---|---|
| B1 | 26,000 (20,000) | `MATCH (d:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE c`, one transaction | 2.06 s; 2.55 s on a second run | ok |
| B2 | 26,000 (20,000) | `delete_chunks_query(10000)`: the same match, `CALL { WITH c DETACH DELETE c } IN TRANSACTIONS OF 10000 ROWS` | 1.40 s; 1.83 s on a second run | ok |
| B3 | 80,000 (62,000) | the one-transaction statement of B1 | 5.24 s | **failed:** `Neo.TransientError.General.MemoryPoolOutOfMemoryError`, "The allocation of an extra 2.0 MiB would use more than the limit 1.4 GiB. Currently using 1.4 GiB. dbms.memory.transaction.total.max threshold reached". 0 chunks deleted |

So on an idle server the biggest live document fits in one transaction, and a document about
three times as big does not. The limit of 1.40 GiB is shared by **all** transactions of the
server, including the chat app's retrieval queries.

How much of the pool B1 used is not settled. A second run sampled `SHOW TRANSACTIONS YIELD
estimatedUsedHeapMemory` every 20 ms: 44 MB for B1 (4 samples), 250 MB for B2 (76 samples,
the outer transaction included). Four samples can miss the peak. If memory grows in proportion
to the chunk count, B3's failure puts B1 above 26,000 / 80,000 × 1.4 GiB ≈ 0.46 GiB. That is
an inference from two points, not a measurement.

## 3. How long does a batched reset take?

Each run: 100 documents of 1,000 chunks (220 parents, 780 embedded leaves), 100,000 chunks,
178,000 relationships and one `_Neodash_Dashboard` node; then the two statements of
`reset_queries(batch)`, timed together.

| Rows per inner transaction | Nodes deleted | Time | Rate |
|---|---|---|---|
| 10,000 | 100,100 | 5.99 s | 16,704 nodes/s |
| 50,000 | 100,100 | 7.57 s | 13,227 nodes/s |

Both left exactly the dashboard node.

The live graph holds 7,515,275 corpus nodes (7,435,393 `:Chunk` and 79,882 `:Document`). At
16,704 nodes/s that is 7,515,275 / 16,704 = 450 s, about 7.5 minutes; at 13,227 nodes/s, 568 s.
**Read 7.5 minutes as a lower bound.** The synthetic store took 653 MB on disk and fit in the
1 GiB page cache; the live store takes 65 GB (`du -sh /data/databases/neo4j` in `ema_neo4j`), so
a live reset reads from disk, and its rate is unknown. The reset is not run on the live graph
in this work unit.

## What follows for the code (TASK-014)

- **Batch the per-document chunk delete, 10,000 rows per inner transaction.** It is what
  `CorpusGraph.delete_document_chunks` does already (`CHUNK_DELETE_BATCH_ROWS`). One
  transaction would fit the biggest live document on an idle server, but it shares the pool
  with every query of the live app, and the batched delete was faster in both runs.
- **Reset with 10,000 rows per inner transaction** (`RESET_BATCH_ROWS`): faster than 50,000 in
  this run, and each transaction holds less.
- **The old reset could not have worked.** It deleted all 7.5 million nodes in one
  transaction; 80,000 chunks already exceed the pool.

## What this did not measure

- The rate of a reset or a replace on the live store, which does not fit in the page cache.
- Deletes while the chat app queries the graph.
- The embedding rate of a replace. The first live replace (TASK-017) records it.
- Any number about retrieval quality: no chunk text or vector of the live graph was read.
