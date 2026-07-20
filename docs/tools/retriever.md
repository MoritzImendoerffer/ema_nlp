# `HierarchicalPGRetriever` — the retriever every tool calls

`harness/indexing/property_graph.py`. A chunk-centric LlamaIndex `BaseRetriever`
over the Neo4j `PropertyGraphIndex`: one Cypher query does vector search,
small-to-big merge and document provenance; optional additional passes walk the
link graph **outward** and the site tree **upward**.

Registered as `@register_retriever("hierarchical")`, selected by an index
profile's `retrieval.strategy` (all shipped profiles use it).

## The passes, in order

| # | Pass | Gate | Origin stamped | Displaces vector hits? |
|---|---|---|---|---|
| 1 | Vector search + small-to-big | always | `vector` | — |
| 2 | Category filter / quota | `categories`, `category_quota` | `vector` | selects within the pool |
| 3 | Link expansion (outward) | `graph.expand` | `link_expansion` | never — additive |
| 4 | Ancestor context (upward) | `graph.ancestors` | `tree_ancestor` | never — additive |

Passes 3 and 4 are seeded from the **surviving vector hits** and dedupe against
everything already returned, so budgets stay predictable: the final node count is
at most `k + max_expand + max_ancestors`.

### 1. Vector search + small-to-big

```cypher
CALL db.index.vector.queryNodes('ema_chunk_embedding', $k, $q) YIELD node, score
WITH node, score, head([(node)<-[:HAS_CHUNK]-(d) | d {…projection…}]) AS doc
WHERE $cats IS NULL OR doc.category IN $cats
RETURN node.id AS id, node.text AS text, score, doc,
       head([(node)<-[:PARENT_OF]-(p) | {id: p.id, text: p.text}]) AS parent
```

Only **leaf** chunks carry embeddings, so the vector index is leaf-only. When
`merge: true` (default) and the leaf has a parent chunk with text, the **parent**
is returned instead — the "small-to-big" trick: match precisely, read widely.
Metadata keeps both ids: `matched_chunk` (the leaf that matched) and `chunk_id`
(what was actually returned).

### 2. Category filter and quota

- **Filter** — `with_categories([...])` returns a view restricted to those
  categories. This is the per-call steering seam `ema_search` uses.
- **Quota** — `category_quota: {scientific_guideline: 2, qa: 1}` guarantees slots
  within the final `k`.

Both draw from an oversampled pool (`k * oversample`) so the filter cannot
starve the result; score order is preserved. Requires `:Document.category`
(stamped at ingest; `scripts/backfill_doc_categories.py` for older graphs).

### 3. Link expansion — outward along `LINKS_TO`

Follows typed link edges from the vector-hit documents and appends the
best-matching chunk of up to `max_expand` linked documents. Edge-property
filters (`link_contexts`, `document_types`) and a target-category restriction
(`expand_categories`, `[]` = any) apply. Each appended node carries
`linked_from = [seed doc ids]` — the provenance the chain view draws as dashed
edges.

Scores are rescaled `(1 + cos) / 2` so they live in the same `[0,1]` range the
Neo4j cosine index returns.

### 4. Ancestor context — upward toward the root

Appends the best-matching chunk of up to `max_ancestors` **site-tree ancestors**
of the vector hits, nearest-first, stamped `tree_ancestor` with `linked_from` =
the seed documents they are ancestors of.

This is a **lookup, not a traversal**: the ancestor chain is read from the
`tree_ancestor_ids` property that [`site_tree.md`](site_tree.md) persists, so no
hop query runs. Ancestors already retrieved are skipped. On a graph without the
backfill it is a silent no-op (no query issued).

Together, 3 + 4 give "walk out along the links **and** up toward the root, with
awareness of each level" in a single `retrieve()` — no extra agent turns.

## Level awareness (always on, no config)

Every returned node carries its place in the site tree:

| Metadata key | Meaning |
|---|---|
| `tree_path` | `/`-joined slot segments, e.g. `medicines/human/EPAR/comirnaty` |
| `tree_depth` | distance from the site root (root = 0) |
| `tree_ancestor_ids` | doc-backed ancestors, root→nearest |

`format_nodes` renders this to the LLM as ` path=/medicines/human/EPAR/comirnaty`
on each result line, so the model can reason about *where* its evidence sits —
sibling documents at one level, a hub above it, leaf PDFs below. Empty/None
before the backfill runs; the rest of the pipeline is unaffected.

## Node metadata contract

`_node_from_row` is the single enrichment point. Every retrieved node carries:

```
source_url, doc_id, title, topic_path, committee, reference_number, source_type,
category, doc_type, audience, site_topic, topic_hubs,
tree_path, tree_depth, tree_ancestor_ids,
chunk_id, matched_chunk, retrieval_origin[, linked_from]
```

Downstream consumers: citations and reference cards (`harness/attribution.py`),
the chain export (`NodeRef`, see [`chain_events.md`](chain_events.md)), the
category steering helpers, and the faithfulness judge's context passages.

## Configuration

Index profiles live in `harness/configs/index/*.yaml`; select with
`EMA_INDEX_PROFILE` or a recipe's `retrieval.index_profile`.

```yaml
retrieval:
  strategy: hierarchical
  k: 10                  # final vector-hit count
  merge: true            # small-to-big parent merge
  oversample: 4          # pool = k * oversample when filtering/quota-ing
  category_quota: {}     # e.g. {scientific_guideline: 2}
  graph:
    max_hops: 1                 # LINKS_TO hop budget for expansion
    edge_types: [links_to]      # relationship label (validated, interpolated)
    link_contexts: [file_component, card_or_listing, inline]
    document_types: []          # edge doc-type filter ([] = any)
    expand: false               # pass 3 on/off
    expand_categories: []       # target-category restriction ([] = any)
    max_expand: 3               # max linked docs appended
    ancestors: false            # pass 4 on/off
    max_ancestors: 3            # max ancestor docs appended
```

Shipped profiles:

| Profile | Passes on | Intent |
|---|---|---|
| `neo4j_hier` (default) | 1 | Plain top-k baseline. |
| `neo4j_steered` | 1–3 | Category steering: quota + link expansion toward guidelines/Q&A. |
| `neo4j_tree` | 1, 3, 4 | Tree traversal: any-category expansion (`max_expand: 6`) + ancestor context. Recipe `tree_agent`. |

`neo4j_tree` deliberately sets `expand_categories: []` — `neo4j_steered`'s
`[scientific_guideline, qa]` would discard exactly the EPAR/news fan-out a
medicine hub page consists of.

## Prerequisites

| Feature | Needs | How to get it |
|---|---|---|
| Category filter/quota/restriction | `:Document.category` | ingest, or `scripts/backfill_doc_categories.py` |
| Ancestor context, `path=` display | `tree_*` properties | `scripts/backfill_site_tree.py` (step `tree` of `update_graph.py`) |
| Link expansion | `LINKS_TO` edges | ingest (`harness.indexing.links`) |

All degrade gracefully: a missing prerequisite means the feature is a no-op, not
an error.

## Failure modes

- **No `tree_ancestor_ids`** → ancestor pass issues no query, returns nothing.
- **Filter matches nothing** → `ema_search` retries unfiltered and says so in a note.
- **Invalid `edge_types`** → `ValueError` at build time (the label is interpolated
  into Cypher, so it is strictly validated against `[A-Z][A-Z0-9_]*`).
- **Expansion finds an already-returned chunk** → deduped, not duplicated.

## Tests

`tests/test_indexing_property_graph.py` (fake store, no Neo4j): projection
contents, metadata mapping, small-to-big merge, oversample/filter, quota
stratification, link expansion provenance + dedupe, ancestor nearest-first
ordering + cap + already-retrieved exclusion + no-op without backfill, and the
expand ∘ ancestors composition. `tests/test_indexing_profiles.py` pins the config
schema.

See also: [`../RETRIEVAL.md`](../RETRIEVAL.md) §7 (steering) and §7.2
(tree-aware retrieval), [`site_tree.md`](site_tree.md).
