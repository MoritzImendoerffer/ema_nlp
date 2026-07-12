#!/usr/bin/env python
"""Backfill ``:Document.audience`` / ``:Document.site_topic`` from page badges.

EMA HTML pages carry curated self-describing header badges (``ema-bg-category``
= audience Human/Veterinary/Corporate/Herbal, ``ema-bg-topic`` = subject
taxonomy) that are already present in the scraped ``web_items.html_raw``
snapshot. New builds stamp both at ingest (``harness.indexing.ingest`` →
``harness.indexing.badges.extract_badges``); this script brings an
already-built graph up to date with the same extractor, so the stored
properties and the ingest path can never disagree.

Only HTML pages have badges — PDF documents are untouched (their ``audience``/
``site_topic`` stay absent). Safe to re-run any time: it re-extracts every
page's badges and overwrites the properties (``SET`` with null clears a
previously-set value if a page lost its badge).

Usage:
    python scripts/backfill_doc_badges.py            # backfill + histograms
    python scripts/backfill_doc_badges.py --dry-run  # histograms only
    python scripts/backfill_doc_badges.py --limit 500  # smoke-test subset
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
from harness.indexing.badges import extract_badges  # noqa: E402
from harness.indexing.chunking import doc_id_for  # noqa: E402
from harness.indexing.ingest import WEB_ITEMS_COLLECTION  # noqa: E402
from harness.indexing.property_graph import (  # noqa: E402
    ensure_document_id_index,
    neo4j_store_from_env,
)

log = logging.getLogger("backfill_doc_badges")


def html_doc_ids(store: Any) -> set[str]:
    """Ids of :Document nodes that can carry badges (HTML pages only)."""
    rows = store.structured_query(
        "MATCH (d:Document) WHERE d.source_type = 'html' RETURN d.id AS id"
    )
    return {r["id"] for r in rows if r.get("id")}

def extract_updates(client: MongoClient[Any], wanted: set[str], *, limit: int = 0) -> list[dict]:
    """One ``{id, audience, site_topic}`` row per indexed HTML page."""
    col = client[MONGO_DB][WEB_ITEMS_COLLECTION]
    updates: list[dict] = []
    seen: set[str] = set()
    cursor = col.find(
        {"html_raw": {"$exists": True, "$ne": []}}, {"url": 1, "html_raw": 1},
        no_cursor_timeout=True,
    )
    try:
        for row in cursor:
            url = row.get("url")
            if isinstance(url, list):  # some web_items rows store url as a 1-element list
                url = url[0] if url else None
            if not url or not isinstance(url, str):
                continue
            doc_id = doc_id_for(url)
            if doc_id not in wanted or doc_id in seen:
                continue
            raw = row.get("html_raw")
            html = raw[0] if isinstance(raw, list) and raw else raw
            if not isinstance(html, str) or not html:
                continue
            seen.add(doc_id)
            badges = extract_badges(html)
            updates.append(
                {"id": doc_id, "audience": badges.audience, "site_topic": badges.site_topic}
            )
            if len(updates) % 5000 == 0:
                log.info("extracted %d / %d", len(updates), len(wanted))
            if limit and len(updates) >= limit:
                break
    finally:
        cursor.close()
    return updates


def backfill(*, batch_size: int = 5000, dry_run: bool = False, limit: int = 0) -> None:
    store = neo4j_store_from_env()
    wanted = html_doc_ids(store)
    log.info("%d indexed HTML documents", len(wanted))

    client: MongoClient[Any] = MongoClient(MONGO_URI)
    try:
        updates = extract_updates(client, wanted, limit=limit)
    finally:
        client.close()

    audiences = Counter(u["audience"] or "(none)" for u in updates)
    topics = Counter(u["site_topic"] or "(none)" for u in updates)
    log.info("extracted badges for %d pages (%d indexed HTML docs had raw HTML)",
             len(updates), len(wanted))
    print(("[dry-run] " if dry_run else "") + "audience histogram:")
    for k, n in audiences.most_common():
        print(f"  {k:14s} {n}")
    print(("[dry-run] " if dry_run else "") + "site_topic histogram (top 20):")
    for k, n in topics.most_common(20):
        print(f"  {k:50s} {n}")
    if dry_run:
        return

    ensure_document_id_index(store)  # the per-id MATCH below must not label-scan
    for start in range(0, len(updates), batch_size):
        chunk = updates[start : start + batch_size]
        store.structured_query(
            "UNWIND $rows AS r MATCH (d:Document {id: r.id}) "
            "SET d.audience = r.audience, d.site_topic = r.site_topic",
            param_map={"rows": chunk},
        )
        log.info("backfilled %d / %d", min(start + batch_size, len(updates)), len(updates))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--dry-run", action="store_true",
                        help="extract + print histograms, write nothing")
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after N pages (smoke test); 0 = all")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    backfill(batch_size=args.batch_size, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
