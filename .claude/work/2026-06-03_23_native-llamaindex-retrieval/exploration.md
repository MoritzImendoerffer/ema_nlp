# Exploration — native LlamaIndex retrieval (replace the custom retriever)

**Directive (user, 2026-06-03):** use **LlamaIndex native retrieval strategies**; do **not**
build custom strategies; if customization is needed, do it **using LlamaIndex tools** (extend
LlamaIndex classes, don't hand-roll).

**Bottom line up front:** what we have today (`HierarchicalPGRetriever`) is a *custom* `BaseRetriever`
running hand-rolled Cypher — it does **not** meet the directive. Work unit 22's plan (more custom
Cypher for links) also doesn't — **superseded**. Native retrieval is achievable, but a hard API
fact (below) means it needs a small, *LlamaIndex-class* adaptation, not a drop-in.

## 1. Why "native, as-is" does not work (confirmed in installed source, v0.14.22)

Native `VectorContextRetriever.retrieve_from_graph` (`…/property_graph/sub_retrievers/vector.py`):
```python
if self._graph_store.supports_vector_queries:        # our Neo4j store: TRUE
    result = self._graph_store.vector_query(vsq)      # searches the __Entity__ vector index
    kg_nodes, scores = result
    triplets = self._graph_store.get_rel_map(kg_nodes, depth=self._path_depth, limit=self._limit)
elif self._vector_store is not None:                  # ONLY if the store can't do vectors
    query_result = self._vector_store.query(vsq)      # ← our chunk index would go here…
    kg_nodes = self._graph_store.get(ids=self._get_kg_ids(query_result.nodes))
    triplets  = self._graph_store.get_rel_map(kg_nodes, depth=self._path_depth, limit=self._limit)
```

Facts about **our** graph (verified live):
- `:Chunk` nodes carry labels `['__Node__','Chunk']` — **not `__Entity__`**. Their 5.82M embeddings
  live in the `ema_chunk_embedding` index (label `Chunk`).
- `Neo4jPropertyGraphStore.vector_query` is hardcoded to `FOR (m:__Entity__) ON m.embedding`
  (the `entity` index). Our 79,882 `__Entity__` nodes are the **Document** entity nodes and are
  **unembedded** (`embed_kg_nodes=False`).
- `supports_vector_queries = True` (plain class bool), so the `elif vector_store` branch is **never
  reached** — passing `vector_store=<our chunks>` is silently ignored.

⇒ A native `VectorContextRetriever` over our store vector-searches the empty `__Entity__` index.
This is precisely the LIR-008 blocker, now root-caused at the line level.

## 2. Native building blocks available (installed, v0.14.22)
- `VectorContextRetriever` (native): `similarity_top_k`, **`path_depth`** (graph hops), `limit`
  (caps `get_rel_map`, default 30 — the native hub-blowup guard), `include_text`, `vector_store`.
- `PropertyGraphIndex.as_retriever(sub_retrievers=[…])` — composes sub-retrievers natively.
- `get_rel_map(nodes, depth, limit, ignore_rels)` — native N-hop neighbour expansion.
- `AutoMergingRetriever`, `RecursiveRetriever`, `QueryFusionRetriever` — installed.
- `Neo4jVectorStore` (`llama-index-vector-stores-neo4j`) — **NOT installed**.

## 3. Two native-compliant options

### Option 1 — native `VectorContextRetriever` + thin store subclass  ✅ recommended
- Subclass `Neo4jPropertyGraphStore`; override **`vector_query`** (≈20 lines) to query the
  `ema_chunk_embedding` (`:Chunk`) index instead of `__Entity__`, returning `:Chunk` LabelledNodes
  + scores. (Extending a LlamaIndex class = "customization using LlamaIndex tools" — within the
  directive. The *retrieval strategy* stays the native `VectorContextRetriever`.)
- Build the retriever natively:
  `VectorContextRetriever(graph_store=ChunkPGStore(...), similarity_top_k=k, path_depth=d, include_text=True)`
  wrapped via `PropertyGraphIndex.as_retriever(sub_retrievers=[…])`.
- The native `get_rel_map(depth=d, limit=L)` then expands from the matched chunk: depth-1
  reaches its Document (`HAS_CHUNK`) + parent/child (`PARENT_OF` = small-to-big); deeper reaches
  `LINKS_TO` neighbours. Capped by `limit`.
- **Reuses the built graph + embeddings — no rebuild.** Delete the custom `HierarchicalPGRetriever`.
- **Tradeoff:** native expansion is a `limit`-capped, generic triplet neighbourhood (not the
  query-relevance-ranked top-M of WU-22's custom design). Coarser, but standard and native. The
  small-to-big "return the parent instead of the leaf" nicety also changes — native returns the
  matched node + its neighbourhood as context, not a parent-substituted node.
- **Risk:** retrieval *shape/quality* of native `get_rel_map` over our schema is unproven → spike first.

### Option 2 — rebuild to canonical `VectorStoreIndex` + `Neo4jVectorStore` + `AutoMergingRetriever`
- The fully-blessed hierarchical pattern (the NVIDIA notebook the user shared): leaf chunks in a
  `Neo4jVectorStore`, the full hierarchy in a docstore, `AutoMergingRetriever` for small-to-big,
  `RecursiveRetriever`/IndexNodes for links.
- **All-native retrievers**, no subclassing. **But:** install `llama-index-vector-stores-neo4j`,
  **re-index** chunks into the vector-store + docstore shape (a rebuild; embeddings *might* be
  reusable), and model links as IndexNode references. Highest cost + risk; throws away the
  PropertyGraphIndex build we just finished.

## 4. Recommendation
**Option 1.** It honours the directive (native `VectorContextRetriever`; the only customization is
subclassing a LlamaIndex store), reuses the ~day-long build, and is the lowest-risk path off the
custom retriever. **Spike first** (timeboxed): subclass `vector_query`, stand up the native
retriever, run 3 real queries, and judge whether native `path_depth`/`get_rel_map` expansion gives
acceptable small-to-big + link context — *before* deleting the custom retriever or committing to
tuning. If the native expansion is unacceptable, escalate to Option 2.

## 5. Key files
- NEW `harness/indexing/pg_store.py` (or in `property_graph.py`): `ChunkVectorPGStore(Neo4jPropertyGraphStore)`
  overriding `vector_query` → `ema_chunk_embedding`.
- `harness/indexing/property_graph.py`: `build_hierarchical_retriever` → return a native
  `VectorContextRetriever`/`PropertyGraphIndex.as_retriever`; **delete `HierarchicalPGRetriever`**.
- `harness/configs/index/neo4j_hier.yaml`: map profile knobs → `similarity_top_k`/`path_depth`/`limit`.
- `harness/workflows/*`: unaffected (already consume a `BaseRetriever` via `.aretrieve()`).
- Tests: replace the custom-retriever assertions with native-retriever behaviour + a live spike.

## 6. Carry-over (independent of the above)
- Query-cache hygiene from WU-22 (clear 15 stale pre-refactor entries + a disable toggle) — still
  valid, still explains "embedded query did nothing." Fold in here as a low-priority task.
