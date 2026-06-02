# Implementation Plan — leaf-only embedding + fresh rebuild

> Revised 2026-06-02 per user: the explore step auto-generated a plan that only did
> *in-place* remediation. This revision does a **clean stop → wipe → from-scratch rebuild**.

## Overview & scope
Fix the confirmed build defect where **all** hierarchical chunk levels are embedded instead
of **only leaf** chunks (root cause: missing `is_leaf` filter in `property_graph._embed_pass`;
the `HierarchicalNodeParser` itself is correct — see `exploration.md`, corroborated by NVIDIA
GenerativeAIExamples notebook 04 which indexes `leaf_nodes` only). Then **rebuild the Neo4j
graph from scratch** with the fix (and, pending the EPAR decision, without out-of-scope EPARs).

In scope: the embed path, an optional ingest-scope EPAR exclusion, tests, and the fresh rebuild.
Out of scope: chunk-size tuning (the 2048/512/128 ladder is fine — docs are genuinely large,
not over-split) and PDF header/footer boilerplate stripping (separate follow-up).

## Architecture / approach
- **Embed leaves only.** Keep building all-level `:Chunk` nodes (needed for `HAS_CHUNK` /
  `PARENT_OF` and small-to-big merge-up), but only call the embedder on `is_leaf` nodes.
  Parents are upserted with text and no `embedding`. Neo4j's vector index
  (`FOR (c:Chunk) ON (c.embedding)`) automatically covers only nodes that *have* an embedding,
  so it becomes leaf-only with no query-side change.
- **Fresh rebuild, not patching.** Graph already wiped; rebuild with `--full --reset` and the
  GPU throttle (`--pause-every-docs 1000 --pause-seconds 60`).
- **EPAR scope (D1) gates the rebuild.** Excluding EPARs is the bigger size lever (they're the
  largest docs); resolve before launching so we don't run multi-hours twice.

## Task execution plan
| ID | Title | Type | Status | Depends |
|----|-------|------|--------|---------|
| LOE-001 | Cleanup: stop run + wipe graph | cleanup | ✅ done | — |
| LOE-002 | Embed leaf chunks only | fix | pending | LOE-001 |
| LOE-003 | Exclude EPAR docs at ingest | feature | ⨯ skipped (D1=keep) | — |
| LOE-004 | Unit tests (leaf-only) | testing | pending | LOE-002 |
| LOE-005 | Fresh full GPU rebuild (~80k incl. EPARs) + verify | integration | pending | LOE-002, LOE-004 |

**Critical path:** LOE-001 ✅ → LOE-002 → LOE-004 → LOE-005.

## Decision RESOLVED
**D1 — EPAR scope → KEEP (user, 2026-06-02).** EPARs are now in scope for the narrative
retrieval corpus; `CLAUDE.md` + `DECISIONS.md` amended. LOE-003 is skipped; **LOE-005 rebuilds
the full ~80k corpus** (multi-hour/-day GPU run, throttled + resumable). Leaf-only embedding
still cuts ~21% of the embedding work vs. the aborted all-levels run.

## QA strategy
- Unit: mock embedder asserts leaf-only embedding; parents upserted unembedded; (if LOE-003)
  EPAR-pattern docs filtered. Full indexing suite + ruff green.
- Post-rebuild verification: `MATCH (c:Chunk {is_leaf:false}) WHERE c.embedding IS NOT NULL`
  returns 0; leaves all embedded; retriever smoke returns merged parent context with provenance.
- Record final counts in `HISTORY.md` and work unit 20.

## Next
Resolve D1, then `/workflow:next` → LOE-002 (then LOE-004; LOE-003 if excluding; LOE-005 rebuild).
