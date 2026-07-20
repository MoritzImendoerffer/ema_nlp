#!/usr/bin/env python
"""Backfill the site-tree properties on an existing Neo4j graph (idempotent).

Stamps four properties on every ``:Document`` from the generic tree derivation
in ``harness.indexing.site_tree`` (breadcrumb → first-HTML-linker → bucket;
see that module's docstring for the corpus-agnostic algorithm):

- ``tree_parent_id``   — doc id of the parent when doc-backed, ``""`` when the
  parent is a synthetic section
- ``tree_depth``       — tree distance from the site root (root = 0)
- ``tree_path``        — ``/``-joined slot segments, e.g.
  ``medicines/human/EPAR/comirnaty``
- ``tree_ancestor_ids``— doc-backed ancestors, root→nearest

Consumers: ``HierarchicalPGRetriever`` (level display on every retrieved node;
``retrieval.graph.ancestors`` context expansion) and the chain-export tree
view. Safe to re-run any time; **re-run after any LINKS_TO rebuild** (the
linker parenting depends on the edges), same staleness rule as topic_hubs.

Usage:
    python scripts/backfill_site_tree.py            # backfill + depth histogram
    python scripts/backfill_site_tree.py --dry-run  # histogram only
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.indexing.property_graph import (  # noqa: E402
    ensure_document_id_index,
    neo4j_store_from_env,
)
from harness.indexing.site_tree import derive_tree_records  # noqa: E402

log = logging.getLogger("backfill_site_tree")


def fetch_documents(store) -> list[dict]:
    return store.structured_query(
        "MATCH (d:Document) RETURN d.id AS id, d.title AS title, "
        "d.source_url AS source_url, d.topic_path AS topic_path, "
        "d.source_type AS source_type"
    )


def fetch_links(store) -> list[tuple[str, str]]:
    rows = store.structured_query(
        "MATCH (a:Document)-[:LINKS_TO]->(b:Document) RETURN a.id AS s, b.id AS t"
    )
    return [(r["s"], r["t"]) for r in rows]


def backfill(store, *, batch_size: int = 10000, dry_run: bool = False) -> Counter:
    nodes = [dict(r) for r in fetch_documents(store) if r.get("id")]
    edges = fetch_links(store)
    records = derive_tree_records(nodes, edges)
    updates = [
        {
            "id": doc_id,
            "parent": rec.parent_id,
            "depth": rec.depth,
            "path": rec.path,
            "ancestors": list(rec.ancestor_ids),
        }
        for doc_id, rec in records.items()
    ]
    histogram = Counter(u["depth"] for u in updates)
    doc_parented = sum(1 for u in updates if u["parent"])
    log.info(
        "derived %d tree records from %d docs / %d links "
        "(%d doc-parented, depth histogram %s)",
        len(updates), len(nodes), len(edges), doc_parented,
        dict(sorted(histogram.items())),
    )
    if dry_run:
        return histogram
    ensure_document_id_index(store)  # the per-id MATCH below must not label-scan
    for start in range(0, len(updates), batch_size):
        chunk = updates[start : start + batch_size]
        store.structured_query(
            "UNWIND $rows AS r MATCH (d:Document {id: r.id}) "
            "SET d.tree_parent_id = r.parent, d.tree_depth = r.depth, "
            "    d.tree_path = r.path, d.tree_ancestor_ids = r.ancestors",
            param_map={"rows": chunk},
        )
        log.info("backfilled %d / %d", min(start + batch_size, len(updates)), len(updates))
    return histogram


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument(
        "--dry-run", action="store_true", help="derive + print the histogram, write nothing"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    store = neo4j_store_from_env()
    histogram = backfill(store, batch_size=args.batch_size, dry_run=args.dry_run)
    print(("[dry-run] " if args.dry_run else "") + "tree depth histogram:")
    for depth, count in sorted(histogram.items()):
        print(f"  depth {depth:2d}  {count}")


if __name__ == "__main__":
    main()
