#!/usr/bin/env python
"""Enrich Mongo ``document_metadata`` with the authoritative EMA labels.

The canonical post-scrape enrichment step (run after every scrape / export
refresh; idempotent). Two independent passes write one row per URL into the
``document_metadata`` collection (``harness.indexing.document_metadata``):

- **badges** — ``audience`` / ``site_topic`` from the ``ema-bg-*`` header
  badges in ``web_items.html_raw`` (HTML pages only; a page without badges is
  written with nulls so a lost badge is cleared, not left stale);
- **doc-types** — ``doc_type`` from EMA's website-data JSON export (PDFs; the
  ~37 MB export is downloaded to a cache path and reused; every export row is
  written, not just currently-indexed docs).

Downstream: ``harness.indexing.ingest`` joins the rows at ingest (new graph
builds get all three labels on ``:Document``);
``scripts/propagate_metadata_to_graph.py`` patches an existing graph without a
rebuild.

Usage:
    python scripts/enrich_document_metadata.py               # both passes
    python scripts/enrich_document_metadata.py --badges      # badges only
    python scripts/enrich_document_metadata.py --doc-types   # export join only
    python scripts/enrich_document_metadata.py --dry-run     # histograms, no writes
"""

from __future__ import annotations

import argparse
import logging
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from pymongo import MongoClient  # noqa: E402

from config import MONGO_DB, MONGO_URI  # noqa: E402
from harness.indexing.badges import extract_badges  # noqa: E402
from harness.indexing.doc_types import (  # noqa: E402
    DOCUMENTS_JSON_URL,
    parse_document_types_by_url,
)
from harness.indexing.document_metadata import (  # noqa: E402
    bootstrap_indexes,
    upsert_badges,
    upsert_doc_types,
)
from harness.indexing.ingest import WEB_ITEMS_COLLECTION  # noqa: E402

log = logging.getLogger("enrich_document_metadata")

_DEFAULT_CACHE = _REPO / ".tmp" / "ema_documents_export.json"


def _unwrap(value: Any) -> Any:
    return (value[0] if value else None) if isinstance(value, list) else value


def badge_rows(client: MongoClient[Any], *, limit: int = 0) -> list[dict[str, Any]]:
    """One ``{url, audience, site_topic}`` row per web_items page with raw HTML."""
    col = client[MONGO_DB][WEB_ITEMS_COLLECTION]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor = col.find(
        {"html_raw": {"$exists": True, "$ne": []}}, {"url": 1, "html_raw": 1},
        no_cursor_timeout=True,
    )
    try:
        for row in cursor:
            url = _unwrap(row.get("url"))
            html = _unwrap(row.get("html_raw"))
            if not isinstance(url, str) or not url or url in seen:
                continue
            if not isinstance(html, str) or not html:
                continue
            seen.add(url)
            badges = extract_badges(html)
            rows.append(
                {"url": url, "audience": badges.audience, "site_topic": badges.site_topic}
            )
            if len(rows) % 5000 == 0:
                log.info("badges extracted for %d pages ...", len(rows))
            if limit and len(rows) >= limit:
                break
    finally:
        cursor.close()
    return rows


def load_export_text(json_path: Path, *, force_download: bool) -> str:
    """The raw EMA documents JSON export (cached download; NOT committed)."""
    if json_path.exists() and not force_download:
        log.info("using cached export %s (%.1f MB)", json_path, json_path.stat().st_size / 1e6)
        return json_path.read_text(encoding="utf-8")
    log.info("downloading %s", DOCUMENTS_JSON_URL)
    req = urllib.request.Request(DOCUMENTS_JSON_URL, headers={"User-Agent": "ema-nlp-research/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310 (trusted EMA host)
        text = resp.read().decode("utf-8")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(text, encoding="utf-8")
    log.info("saved %s (%.1f MB)", json_path, len(text) / 1e6)
    return text


def run_badges(client: MongoClient[Any], *, dry_run: bool, limit: int) -> None:
    rows = badge_rows(client, limit=limit)
    audiences = Counter(r["audience"] or "(none)" for r in rows)
    topics = Counter(r["site_topic"] or "(none)" for r in rows)
    print(("[dry-run] " if dry_run else "") + f"badges: {len(rows)} pages — audience histogram:")
    for k, n in audiences.most_common():
        print(f"  {k:14s} {n}")
    print(("[dry-run] " if dry_run else "") + "site_topic histogram (top 20):")
    for k, n in topics.most_common(20):
        print(f"  {k:50s} {n}")
    if dry_run:
        return
    written = upsert_badges(rows, client=client)
    log.info("badges pass: upserted %d rows", written)


def run_doc_types(
    client: MongoClient[Any], *, json_path: Path, force_download: bool, dry_run: bool
) -> None:
    by_url = parse_document_types_by_url(load_export_text(json_path, force_download=force_download))
    print(
        ("[dry-run] " if dry_run else "")
        + f"doc-types: {len(by_url)} export records — histogram (top 30):"
    )
    for t, n in Counter(v or "(empty)" for v in by_url.values()).most_common(30):
        print(f"  {t:36s} {n}")
    if dry_run:
        return
    written = upsert_doc_types(by_url, client=client)
    log.info("doc-types pass: upserted %d rows", written)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--badges", action="store_true", help="run only the badges pass")
    parser.add_argument("--doc-types", action="store_true", help="run only the doc_type pass")
    parser.add_argument("--json-path", type=Path, default=_DEFAULT_CACHE,
                        help=f"export file (downloaded if absent; default {_DEFAULT_CACHE})")
    parser.add_argument("--force-download", action="store_true",
                        help="re-download the export even if the cache file exists")
    parser.add_argument("--limit", type=int, default=0,
                        help="badges pass: stop after N pages (smoke test); 0 = all")
    parser.add_argument("--dry-run", action="store_true",
                        help="extract + print histograms, write nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    do_badges = args.badges or not args.doc_types
    do_doc_types = args.doc_types or not args.badges

    client: MongoClient[Any] = MongoClient(MONGO_URI)
    try:
        if not args.dry_run:
            bootstrap_indexes(client=client)
        if do_badges:
            run_badges(client, dry_run=args.dry_run, limit=args.limit)
        if do_doc_types:
            run_doc_types(
                client,
                json_path=args.json_path,
                force_download=args.force_download,
                dry_run=args.dry_run,
            )
    finally:
        client.close()


if __name__ == "__main__":
    main()
