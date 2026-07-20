# Site tree — deriving document hierarchy generically

`harness/indexing/site_tree.py` + `scripts/backfill_site_tree.py`.

The premise: **links between documents encode the knowledge structure of an
organization.** Reports link to SOPs which link to a quality system; EMA pages
link to EPAR PDFs, assessment reports and news. So the corpus is one tree rooted
at the site root, and both retrieval and visualization can traverse it.

Three consumers share this one derivation:

- [`retriever.md`](retriever.md) — ancestor context + per-node level display
- KB map — `scripts/build_graph_map.py --tree` (the radial whole-corpus view)
- Chain export — the per-turn site-tree SVG ([`chain_events.md`](chain_events.md))

## The algorithm (corpus-agnostic)

Given a root, every document takes **exactly one parent** from a priority chain
of parent signals:

1. **Explicit path metadata** — the breadcrumb (`topic_path`, falling back to the
   URL path). The document sits at its path slot, parented by the path prefix. A
   document whose path *is* a section **becomes** that section node rather than
   duplicating it.
2. **First structural linker** — a document with no place of its own (here: PDFs,
   whose `topic_path` is only a flat `documents/<type>` bucket) hangs under the
   first non-leaf document that links to it. Deterministic: smallest linker id.
3. **Flat bucket** — the fallback for documents that are neither placed nor
   linked.

Synthetic `§path` section nodes fill in the prefixes. For a corpus with **no path
metadata at all**, signal 2 applied transitively degrades to BFS layering over
the link graph from the root — levels are then BFS depth.

**Levels are emergent, never enumerated.** A "level" is the sibling set under one
tree node (`tree_path` prefix + `tree_depth`). That is why EPAR,
orphan-designations, paediatric-investigation-plans and the rest come out as
levels without any of them appearing in code — the repo rule that no category is
hardcoded holds by construction.

## API

```python
from harness.indexing.site_tree import (
    site_segments,        # doc -> breadcrumb segments (topic_path | URL fallback)
    build_tree,           # (nodes, edges) -> (section_nodes, children, tree_edges)
    derive_tree_records,  # (nodes, edges) -> {doc_id: TreeRecord}
    tree_layout,          # radial positions (KB map)
    layered_positions,    # left-to-right layered positions (chain SVG)
)
```

`TreeRecord` is what gets persisted:

| Field | Meaning |
|---|---|
| `parent_id` | parent **document** id; `""` when the parent is a synthetic section |
| `depth` | tree distance from the root (root = 0) |
| `path` | `/`-joined slot segments, e.g. `medicines/human/EPAR/comirnaty` |
| `ancestor_ids` | doc-backed ancestors only, root→nearest |

Inputs per node: `id`, `title`, `source_url`, `topic_path`, `source_type`
(+`category` for section labelling). Edges are `(src_id, dst_id)` link pairs.
Everything is pure and offline — no store access, no igraph.

## Persisting it

```bash
python scripts/backfill_site_tree.py --dry-run   # derive + depth histogram, write nothing
python scripts/backfill_site_tree.py             # stamp the graph
```

Writes four properties per `:Document`:

```cypher
UNWIND $rows AS r MATCH (d:Document {id: r.id})
SET d.tree_parent_id = r.parent, d.tree_depth = r.depth,
    d.tree_path = r.path, d.tree_ancestor_ids = r.ancestors
```

Idempotent and fast (seconds over ~80k docs). It is step **`tree`** in
`scripts/update_graph.py` and part of the default steps.

> **Staleness rule:** re-run after any `LINKS_TO` rebuild. Linker parenting
> depends on the edges, so new/changed links move documents in the tree. Same
> rule as `topic_hubs`.

Why precompute rather than derive per query: the derivation needs the whole
document set **and** all link edges (a global "first linker" pass) — seconds
offline, unacceptable per query. This follows the established
precompute-then-lookup pattern (`topic_hubs`, `:Document.category`).

## Live shape (marvin-gpu, 2026-07-20)

```
79,882 records · max depth 7 · 55,911 doc-parented
depth histogram: 1:1165  2:9725  3:23074  4:17117  5:27869  6:833  7:99
```

**55,911 of 79,882 documents are parented by another document**, i.e. the link
graph — not the flat bucket — determines where most PDFs live. Spot check:

```
Comirnaty page  → tree_path=medicines/human/EPAR/comirnaty  depth=4
                  ancestors=[<the /medicines page>]
                  children=51 (its EPAR PDFs, assessment reports, safety updates)
```

## Verifying by hand

```cypher
// where does one document sit?
MATCH (d:Document) WHERE d.source_url ENDS WITH '/medicines/human/EPAR/comirnaty'
RETURN d.tree_path, d.tree_depth, d.tree_parent_id, d.tree_ancestor_ids;

// what did it adopt?
MATCH (c:Document {tree_parent_id: $id}) RETURN c.title, c.tree_depth LIMIT 20;

// sanity: depth distribution + orphan check
MATCH (d:Document) RETURN d.tree_depth AS depth, count(*) ORDER BY depth;
```

## Tests

`tests/test_site_tree.py` — parenting rules (breadcrumb, doc-occupies-section,
PDF-under-linker, bucket fallback), depths, ancestor ordering/doc-backedness,
one record per document, determinism, and `layered_positions` completeness +
depth monotonicity. `tests/test_graph_map.py` passes **unchanged** from before
the module existed, which is what proves the extraction was behavior-neutral.
