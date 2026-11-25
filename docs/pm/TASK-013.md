---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-013
status: todo
kind: measurement
title: "Measure the deletes and the reset on a throwaway Neo4j"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-013 — Measure the deletes and the reset on a throwaway Neo4j

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Open measurements of the exploration (lines 517-521): whether a deleted chunk leaves the vector index at once (5.1), the batch size for node deletes (5.3), and how long a batched reset takes. The third one, the backfill's duration and the embedding rate of a replace, needs the live stores and goes to TASK-015 (read-only) and TASK-016/017.

This is a systems measurement, not a comparison of recipes: no benchmark items, no models, no judge, 0 paid calls, no GPU. The 'arms' are the batch sizes.

The lead session asked to be told before the container starts. Neo4j community holds one database, and deploy/neo4j/docker-compose.yml fixes `container_name: ema_neo4j` and its volumes (exploration 5.4), so the scratch instance is a `docker run` with its own name and port, written into the eval page. The code reads NEO4J_URI from the environment (property_graph.py:72); check that the env file loaded by config.py does not override a NEO4J_URI set in the shell (python-dotenv's default is override=False) before any write.

Synthetic data, made with plain Cypher: one :Document with 26,000 :__Node__:Chunk nodes (the biggest live document has 25,916), 2,000 characters of text each, a 1,024-float embedding on 20,000 leaves, HAS_CHUNK and PARENT_OF edges, the vector index created as `ensure_chunk_vector_index` does, plus a _Neodash_Dashboard node. For the reset rate, a few hundred thousand chunk nodes are enough to scale from.

The live upsert path uses APOC (`apoc.map.clean`, neo4j_property_graph.py:386). If the integration test runs the build's upsert, start the container with NEO4J_PLUGINS='["apoc"]' as the live compose file does (line 22).

## Acceptance criteria

- [ ] A container `ema_neo4j_scratch` (image neo4j:5.26, bolt on host port 7688, no named volume, heap 2G, transaction memory limit 1.4G as on the live server) ran the measurement and was removed afterwards; `docker ps` lists ema_neo4j and ema_neodash unchanged before and after
- [ ] `EMA_SCRATCH_NEO4J_URI=bolt://localhost:7688 .venv/bin/python -m pytest -m integration tests/test_graph_ops_neo4j.py` passes; without the variable every test in that file is skipped, and a URI with port 7687 makes the tests fail before they connect
- [ ] docs/eval/2026-11-25_graph_delete_measurement.md answers with the query beside each number: (1) does a deleted chunk leave the vector index ema_chunk_embedding at once; (2) the duration and outcome of deleting one document with 26,000 chunks in one transaction and in batches; (3) the rate of the batched reset in nodes per second for 10,000 and 50,000 rows per batch, and the hours that rate gives for the 7,515,275 corpus nodes of the live graph
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]], [[TASK-006]], [[TASK-007]], [[TASK-008]]

## Files it touched

- `tests/test_graph_ops_neo4j.py`
- [[2026-11-25_graph_delete_measurement]] — `docs/eval/2026-11-25_graph_delete_measurement.md`
