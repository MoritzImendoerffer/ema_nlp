# Exploration — graph-aware retrieval (LINKS_TO traversal gap)

**User finding (2026-06-03):** "the chat interface does not really use the recursive
retriever and the graph structure; the embedded query did nothing." **Verdict: a real
gap.** The retriever connects to the chat path, but its graph value-add (the link-graph
traversal that is the project's stated cornerstone) is not implemented.

## 1. Current state — what is actually wired

The chat retrieval chain **does** reach `HierarchicalPGRetriever` (the user's "not used"
is imprecise but their instinct is right — see §2):

```
app.py _build_session_workflow
  → load_index_profile("neo4j_hier")
  → build_retriever(profile, open_index(profile))          # registry.py
       dispatch on profile.retrieval.strategy == "hierarchical"
  → build_hierarchical_retriever(profile, index)           # property_graph.py
  → HierarchicalPGRetriever(store, embed, k=10, merge=True)
  → get_workflow("simple_rag", retriever=…)                # each retrieve step: retriever.aretrieve()
```

`HierarchicalPGRetriever._QUERY` (the one Cypher it runs):
```
CALL db.index.vector.queryNodes('ema_chunk_embedding', $k, $q) YIELD node, score
RETURN node.id, node.text, score,
  head([(node)<-[:HAS_CHUNK]-(d) | d.source_url]) AS source_url,   # provenance ✅
  head([(node)<-[:HAS_CHUNK]-(d) | d.id])         AS doc_id,       # provenance ✅
  head([(node)<-[:PARENT_OF]-(p) | {id:p.id, text:p.text}]) AS parent   # small-to-big ✅
```

So today retrieval = **flat vector search over leaf chunks + one-step parent merge +
provenance.** That is the *chunk hierarchy* (PARENT_OF) — but **not** the *cross-document
link graph* (LINKS_TO).

## 2. The gap (root cause)

- `profile.retrieval.graph` IS fully parsed: `GraphRetrievalConfig(max_hops=1,
  edge_types=["links_to"])` (`profiles.py:107`), set in `neo4j_hier.yaml` (`graph: {max_hops:1,
  edge_types:[links_to]}`), with the profile comment claiming *"small-to-big merge + links-to
  traversal (v1)."*
- But **`build_hierarchical_retriever` passes only `k` + `merge`** to the retriever and
  **`HierarchicalPGRetriever` never reads `profile.retrieval.graph`.** The config is plumbed
  to the door and dropped on the floor.
- **LIR-008's acceptance criterion** literally says *"vector search on leaf chunks → merge up
  via parent/child → **1-hop links-to expansion**"* — the third clause was never implemented,
  yet LIR-008 (and work unit 20) were marked complete. Same failure mode the project keeps
  hitting (the MIGR-018..025 "link graph documented as shipped but never built"). The 1.72M
  `LINKS_TO` edges we built (and debugged the `:Document(id)` index for) are dead weight at
  query time.

**Does the current plan cover it? NO.** Work unit 20 is closed; no pending task delivers
links-to traversal. A new task set is required → this work unit.

## 3. Secondary finding — the semantic query cache ("embedded query did nothing")

`app.py:_embed_query_sync` embeds the query **only** for the FAISS semantic cache +
few-shot; the *retriever* re-embeds separately. The cache (`harness.query_cache`, 15 entries)
runs **before** retrieval: on a ≥0.88-similar hit it pops an `AskActionMessage`
("Use cached / Run full pipeline") and, if "use cached," `return`s — skipping the new
retriever entirely. Those 15 entries are almost certainly **pre-refactor** (answers over the
old FAISS/pgvector corpus), so during a fresh-graph test the cache either interrupts with a
stale-answer prompt or serves one. This explains the "embedded query did nothing" experience
even though the retriever's own vector search works (verified: 3 queries, scores 0.90–0.93).

## 4. Architecture — bounded, query-relevant 1-hop LINKS_TO expansion

**Intent (cornerstone, 2026-05-27):** *"By traversing the links upwards, relevant context
might be discovered in a structural way."* So: after vector search lands on chunks in some
docs, follow those docs' `LINKS_TO` edges and pull in the part of each linked doc most
relevant to the query — context semantic search alone missed.

**Critical constraint discovered:** out-degree is wildly skewed — hub pages
(`…/whats-new/…`) link to **456–533** docs. Following "all neighbors" would flood the result
set. So expansion must be **globally top-M by query relevance**, not per-neighbor.

**Design (stays in the existing "few Cyphers" style; `vector.similarity.cosine` confirmed
available on Neo4j 5.26):**

1. Seed = current behaviour (top-`k` leaf hits → parent merge → provenance). Unchanged.
2. From the seed hits' `doc_id`s, one expansion Cypher (gated on `graph.max_hops > 0`):
   ```
   UNWIND $seed_doc_ids AS sid
   MATCH (a:Document {id: sid})-[:LINKS_TO]->(b:Document)-[:HAS_CHUNK]->(c:Chunk {is_leaf:true})
   WHERE NOT b.id IN $seed_doc_ids                       // don't re-pull seed docs
   WITH b, c, vector.similarity.cosine(c.embedding, $q) AS sim
   ORDER BY sim DESC
   WITH b, collect({id:c.id, text:c.text, sim:sim})[0] AS best   // top chunk per neighbour doc
   RETURN b.source_url, b.id, best.id, best.text, best.sim
   ORDER BY best.sim DESC LIMIT $m                       // GLOBAL top-M (caps hub blow-up)
   ```
   (Optionally small-to-big the expanded chunk too, for parity.)
3. Merge: `k` direct hits + up to `M` expanded hits, deduped by node id. Expanded nodes get a
   **decayed** score (`link_decay * sim`, default 0.5) and `metadata.via_link = True` +
   `metadata.linked_from = <seed source_url>`, so they rank below direct matches, are
   visibly attributable, and the LLM/citations can distinguish them.
4. Params from `profile.retrieval.graph` (+ small additions): `max_hops` (0 disables — free
   ablation toggle), `edge_types` (today only `links_to`; keep generic), `expand_m` (default
   5), `link_decay` (default 0.5).

**Why custom Cypher, not LlamaIndex `RecursiveRetriever`/`AutoMergingRetriever`:** LIR-008's
spike already chose a custom one-Cypher retriever over the native ones (the native vector
retriever only searches the `__Entity__` index; AutoMerging needs a docstore we don't keep).
A second bounded Cypher is the consistent, lowest-risk extension; the `:Document(id)` index
(built in LOE) makes the `MATCH (a:Document {id})` fast.

**Performance:** bounded by (#seed docs) × (their neighbours' chunks) for the cosine, then
global LIMIT M. Cap neighbours scanned if needed (e.g. only first N neighbours per seed) —
but the per-neighbour `collect[0]` + global LIMIT already bounds output. Verify latency live.

## 5. Key files
- `harness/indexing/property_graph.py` — `HierarchicalPGRetriever` (add expansion),
  `build_hierarchical_retriever` (pass `profile.retrieval.graph`).
- `harness/indexing/profiles.py` — `GraphRetrievalConfig` (maybe add `expand_m`/`link_decay`).
- `harness/configs/index/neo4j_hier.yaml` — graph block (add the new knobs).
- `tests/test_indexing_property_graph.py` — extend with a links-to expansion test (fake store).
- `harness/query_cache.py` + `app.py` — secondary: stale-cache hygiene / a disable toggle.

## 6. Open design choices (defaults chosen; tunable, not blocking)
- **Additive vs. competitive**: recommend *additive* (k direct + up to M link chunks) so link
  traversal ADDS missed context rather than displacing top matches.
- **Neighbour-chunk pick**: query-relevant top chunk per neighbour (recommended) vs. the
  neighbour's root/2048 chunk (cheaper, coarser). Recommend query-relevant.
- **M / decay defaults**: M=5, decay=0.5 — revisit once the benchmark exists.
