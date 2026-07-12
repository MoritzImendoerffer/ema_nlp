#!/usr/bin/env python
"""Backfill ``:Document.category`` on an existing Neo4j graph (idempotent).

Retrieval steering (category filter / quota / link-graph expansion — see
``docs/RETRIEVAL.md``) filters on the persisted ``category`` property in Cypher.
New builds stamp it at ingest (``harness.indexing.property_graph._entity_for``);
this script brings an already-built graph up to date using the same
table-driven rules (``harness.retrieval.doc_categories.classify_source``), so
the stored property and the runtime classifier can never disagree.

Safe to re-run any time (e.g. after extending the classification rules): it
recomputes every document's category and overwrites the property. Chunks,
embeddings, and edges are untouched.

Usage:
    python scripts/backfill_doc_categories.py            # backfill + histogram
    python scripts/backfill_doc_categories.py --dry-run  # histogram only
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
from harness.retrieval.doc_categories import classify_source  # noqa: E402

log = logging.getLogger("backfill_doc_categories")


def fetch_documents(store) -> list[dict]:
    return store.structured_query(
        "MATCH (d:Document) RETURN d.id AS id, d.source_url AS url, d.topic_path AS topic"
    )


def backfill(store, *, batch_size: int = 10000, dry_run: bool = False) -> Counter:
    rows = fetch_documents(store)
    updates = [
        {"id": r["id"], "category": classify_source(r.get("url") or "", r.get("topic") or "")}
        for r in rows
        if r.get("id")
    ]
    histogram = Counter(u["category"] for u in updates)
    log.info("classified %d documents: %s", len(updates), dict(histogram))
    if dry_run:
        return histogram
    ensure_document_id_index(store)  # the per-id MATCH below must not label-scan
    for start in range(0, len(updates), batch_size):
        chunk = updates[start : start + batch_size]
        store.structured_query(
            "UNWIND $rows AS r MATCH (d:Document {id: r.id}) SET d.category = r.category",
            param_map={"rows": chunk},
        )
        log.info("backfilled %d / %d", min(start + batch_size, len(updates)), len(updates))
    return histogram


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument(
        "--dry-run", action="store_true", help="classify + print the histogram, write nothing"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    store = neo4j_store_from_env()
    histogram = backfill(store, batch_size=args.batch_size, dry_run=args.dry_run)
    print(("[dry-run] " if args.dry_run else "") + "category histogram:")
    for category, count in histogram.most_common():
        print(f"  {category:22s} {count}")


if __name__ == "__main__":
    main()
