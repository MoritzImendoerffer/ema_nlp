# Requirements — native LlamaIndex retrieval

## Problem
The chat retriever is a custom `BaseRetriever` (`HierarchicalPGRetriever`, hand-rolled Cypher),
which violates the directive "use native LlamaIndex retrieval strategies; customize only via
LlamaIndex tools." Native `VectorContextRetriever` can't retrieve our chunks as-is because the
Neo4j store's `vector_query` targets the `__Entity__` index, not our `:Chunk`/`ema_chunk_embedding`.

## Functional requirements (Option 1 — recommended)
- **FR1** The chat/workflow retriever is a **native LlamaIndex retriever** (`VectorContextRetriever`
  via `PropertyGraphIndex.as_retriever`), not a custom `BaseRetriever` subclass.
- **FR2** Vector search hits our **chunk** embeddings. Achieved by subclassing
  `Neo4jPropertyGraphStore` and overriding `vector_query` to use `ema_chunk_embedding` (`:Chunk`).
  This is the *only* customization, and it extends a LlamaIndex class.
- **FR3** Graph context (small-to-big via `PARENT_OF`, links via `LINKS_TO`) comes from the native
  `path_depth`/`get_rel_map` expansion — no bespoke traversal code.
- **FR4** Retrieval profile knobs (`k`, and a `path_depth`/`limit`) are read from the profile.
- **FR5** The custom `HierarchicalPGRetriever` is removed once the native path is verified.
- **FR6** Reuse the existing graph + embeddings (no rebuild) unless the spike forces Option 2.

## Non-functional
- **NFR1** No retrieval-quality regression vs. today's vector+parent-merge on the smoke queries
  (judged in the spike on the real graph).
- **NFR2** No chat-path latency regression.
- **NFR3** Workflows unchanged (they already consume a `BaseRetriever.aretrieve()`).

## Acceptance criteria
- [ ] Spike: native `VectorContextRetriever` (+ store subclass) returns relevant, provenance-bearing
      results on ≥3 real EMA queries over the built graph; decision recorded (proceed vs Option 2).
- [ ] `build_hierarchical_retriever` returns a native retriever; `HierarchicalPGRetriever` deleted.
- [ ] Small-to-big + 1-hop links context demonstrably present via `path_depth` (or recorded as a
      known native limitation if `get_rel_map` can't express it cleanly).
- [ ] Tests updated to the native retriever; ruff + indexing suite green.
- [ ] `docs/RETRIEVAL.md` updated to describe the native retriever (no custom-Cypher claims).

## Risks
- **R1** Native `get_rel_map` expansion may be too coarse (limit-capped generic triplets, no
  query-relevance ranking) or may not surface linked-doc *chunks* at a useful `path_depth`. → spike
  gates this; fallback is Option 2 (rebuild) or an accepted "vector + small-to-big only, links later."
- **R2** `vector_query` override must return LabelledNodes whose ids match graph node ids so
  `get_rel_map` traverses correctly — verify in the spike.
- **R3** Option 2 (if forced) is a multi-hour rebuild + new store dependency.

## Out of scope
- Multi-hop > native `path_depth`; typed/weighted edges; benchmark tuning (no benchmark yet).

## Decision needed (blocks committing the plan)
**Option 1 (adapt: native retriever + store subclass, no rebuild) vs Option 2 (rebuild to
VectorStoreIndex + Neo4jVectorStore + AutoMergingRetriever).** Recommend Option 1, spike-first.
