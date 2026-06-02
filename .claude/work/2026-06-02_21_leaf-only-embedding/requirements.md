# Requirements — leaf-only embedding fix

## Problem
The hierarchical index build embeds **all** chunk levels (2048/512/128‑token) instead of
**only leaf** chunks. Root cause is a missing `is_leaf` filter in
`property_graph.py::_embed_pass` — **not** a `HierarchicalNodeParser` behaviour (the splitter
correctly emits all levels; the canonical pattern embeds leaves only). See `exploration.md`.

## Functional requirements
- **FR1** The build embeds **only leaf** chunks (`is_leaf == true`). Parent (mid/root) chunks
  are still stored as `:Chunk` with their **text** and `HAS_CHUNK` / `PARENT_OF` edges, but
  carry **no `embedding`** property.
- **FR2** The Neo4j vector index (`ema_chunk_embedding`) therefore covers **leaf chunks only**.
  Its dimensionality is taken from a leaf embedding.
- **FR3** Small‑to‑big retrieval is unchanged in intent: a matched leaf still merges up to its
  immediate parent via `PARENT_OF` (parent text is read from the node, not re‑embedded).
- **FR4** Resume/idempotency preserved: re‑running the build does not duplicate nodes/edges or
  re‑embed completed docs.
- **FR5** Provide a remediation path for an **already‑built** graph that drops surplus
  non‑leaf embeddings **without re‑embedding** leaves (single Cypher `REMOVE`), for the case
  where a full `--reset` rebuild is not chosen.

## Non-functional
- **NFR1** No measurable regression in retrieval relevance on the smoke queries; expect
  *improved* precision and ~21% fewer vectors.
- **NFR2** ~21% less embedding compute on a full build.
- **NFR3** Behaviour matches the documented design (`docs/RETRIEVAL.md`, chunker docstring,
  LIR‑008 spike "vector search on leaf chunks").

## Acceptance criteria
- [ ] `_embed_pass` embeds only leaf ChunkNodes; parents upserted with no embedding.
- [ ] Unit test (mock embedder) asserts the embedder is called with **only leaf texts**, and
      that parents are still upserted (with text + `PARENT_OF`).
- [ ] After a fresh subset build: `MATCH (c:Chunk {is_leaf:false}) WHERE c.embedding IS NOT NULL
      RETURN count(c)` = 0; leaf count > 0 and all leaves embedded.
- [ ] Retriever smoke test still returns relevant, provenance‑bearing parent context.
- [ ] Remediation Cypher documented/scripted and verified to drop non‑leaf vectors from the index.
- [ ] `ruff` + full indexing test suite green.

## Open decisions (block the *rebuild*, not the code fix)
- **D1 — EPAR scope.** 22.7% of clean docs are out‑of‑scope EPAR assessment reports
  (`CLAUDE.md` V1: "No EPARs"). Exclude at ingest, or change scope? Decided separately; if
  excluded, fold the filter into the same `--reset` rebuild as this fix.
- **D2 — Current run.** Stop the running all‑levels build now and rebuild clean, vs. let it
  finish and remediate with the REMOVE sweep. Depends on D1 (a scope filter ⇒ `--reset` anyway).

## Out of scope
- Page‑header/footer boilerplate stripping (separate, minor; tracked as a follow‑up).
- Chunk‑size tuning (the 128/512/2048 ladder is fine; not over‑splitting).
