#!/usr/bin/env python
"""Propagate ``document_metadata`` labels from Mongo onto the Neo4j graph.

Patches an **existing** graph with the authoritative labels
(``:Document.doc_type`` / ``.audience`` / ``.site_topic``) and the precomputed
topic-subgraph memberships (``:Document.topic_hubs``) from the canonical
Mongo ``document_metadata`` collection — no rebuild, no re-embedding. New
builds don't need this: ``harness.indexing.ingest`` joins the same rows at
ingest, so the stored graph and a fresh build can never disagree about a label.

Run it after ``scripts/enrich_document_metadata.py`` whenever the labels were
refreshed (new scrape, new JSON export) — or after
``scripts/manage_topic_hubs.py build`` recomputed memberships — and the graph
should pick them up without rebuilding. Safe to re-run: each label group is SET
from its row (badge nulls overwrite, clearing labels a page lost; ``doc_type``
is only touched on rows the export pass stamped; ``topic_hubs`` is SET whole,
so lost memberships clear too).

This replaces the former ``scripts/backfill_doc_types.py`` +
``scripts/backfill_doc_badges.py``, which re-derived labels from the raw
sources on every run instead of reading the canonical collection.

Usage:
    python scripts/propagate_metadata_to_graph.py            # patch the graph
    python scripts/propagate_metadata_to_graph.py --dry-run  # coverage report only
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from pymongo import MongoClient  # noqa: E402

from config import MONGO_DB, MONGO_URI  # noqa: E402
from harness.indexing.document_metadata import COLLECTION  # noqa: E402
from harness.indexing.property_graph import (  # noqa: E402
    ensure_document_id_index,
    neo4j_store_from_env,
)

log = logging.getLogger("propagate_metadata_to_graph")


def graph_doc_ids(store: Any) -> set[str]:
    rows = store.structured_query("MATCH (d:Document) RETURN d.id AS id")
    return {r["id"] for r in rows if r.get("id")}


def load_rows(
    client: MongoClient[Any], wanted: set[str]
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split enrichment rows for indexed docs into (badge, doc_type, topic_hub) rows.

    A row only carries a label group its provenance says was stamped — so a
    doc_type-only row never nulls out badges and vice versa.
    """
    col = client[MONGO_DB][COLLECTION]
    badge_rows: list[dict] = []
    doc_type_rows: list[dict] = []
    topic_hub_rows: list[dict] = []
    cursor = col.find(
        {},
        {
            "doc_id": 1, "doc_type": 1, "audience": 1, "site_topic": 1,
            "topic_hubs": 1, "provenance": 1,
        },
        no_cursor_timeout=True,
    )
    try:
        for row in cursor:
            doc_id = row.get("doc_id")
            if not doc_id or doc_id not in wanted:
                continue
            prov = row.get("provenance") or {}
            if "badges" in prov:
                badge_rows.append(
                    {
                        "id": doc_id,
                        "audience": row.get("audience"),
                        "site_topic": row.get("site_topic"),
                    }
                )
            if "doc_type" in prov:
                doc_type_rows.append({"id": doc_id, "doc_type": row.get("doc_type")})
            if "topic_hubs" in prov:
                topic_hub_rows.append({"id": doc_id, "topic_hubs": row.get("topic_hubs") or []})
    finally:
        cursor.close()
    return badge_rows, doc_type_rows, topic_hub_rows


def _apply(store: Any, rows: list[dict], set_clause: str, *, batch_size: int) -> None:
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        store.structured_query(
            f"UNWIND $rows AS r MATCH (d:Document {{id: r.id}}) SET {set_clause}",
            param_map={"rows": chunk},
        )
        log.info("applied %d / %d", min(start + batch_size, len(rows)), len(rows))


def propagate(*, batch_size: int = 5000, dry_run: bool = False) -> None:
    store = neo4j_store_from_env()
    wanted = graph_doc_ids(store)
    log.info("%d :Document nodes in the graph", len(wanted))

    client: MongoClient[Any] = MongoClient(MONGO_URI)
    try:
        badge_rows, doc_type_rows, topic_hub_rows = load_rows(client, wanted)
    finally:
        client.close()

    prefix = "[dry-run] " if dry_run else ""
    print(
        f"{prefix}join coverage: badges {len(badge_rows)} docs, "
        f"doc_type {len(doc_type_rows)}, topic_hubs {len(topic_hub_rows)} "
        f"/ {len(wanted)} indexed docs"
    )
    print(f"{prefix}audience histogram:")
    for k, n in Counter(r["audience"] or "(none)" for r in badge_rows).most_common():
        print(f"  {k:14s} {n}")
    print(f"{prefix}doc_type histogram (top 30):")
    for t, n in Counter(r["doc_type"] or "(empty)" for r in doc_type_rows).most_common(30):
        print(f"  {t:36s} {n}")
    if topic_hub_rows:
        print(f"{prefix}topic_hubs histogram:")
        hub_counts = Counter(k for r in topic_hub_rows for k in r["topic_hubs"])
        for k, n in hub_counts.most_common():
            print(f"  {k:36s} {n}")
    if not badge_rows and not doc_type_rows and not topic_hub_rows:
        log.warning("nothing to propagate — run scripts/enrich_document_metadata.py first")
        return
    if dry_run:
        return

    ensure_document_id_index(store)  # the per-id MATCH below must not label-scan
    log.info("propagating badges (%d rows)", len(badge_rows))
    _apply(
        store, badge_rows, "d.audience = r.audience, d.site_topic = r.site_topic",
        batch_size=batch_size,
    )
    log.info("propagating doc_type (%d rows)", len(doc_type_rows))
    _apply(store, doc_type_rows, "d.doc_type = r.doc_type", batch_size=batch_size)
    log.info("propagating topic_hubs (%d rows)", len(topic_hub_rows))
    _apply(store, topic_hub_rows, "d.topic_hubs = r.topic_hubs", batch_size=batch_size)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--dry-run", action="store_true",
                        help="report join coverage + histograms, write nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    propagate(batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
