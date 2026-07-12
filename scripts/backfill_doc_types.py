#!/usr/bin/env python
"""Backfill ``:Document.doc_type`` from EMA's website-data JSON export.

EMA's own document export carries an authoritative ``type`` per document
(``harness.indexing.doc_types``), keyed by ``document_url``. Hashed to our
``doc_id`` it joins to ~96.6% of the PDF nodes — a first-class document type
that the URL-derived ``category`` and the ``LINKS_TO`` edge ``document_type``
only partially recover. This stamps it as ``:Document.doc_type`` (PDF nodes;
HTML pages are not in the export — they carry ``audience``/``site_topic`` badges
instead, see ``scripts/backfill_doc_badges.py``).

The export is a ~37 MB download; it is NOT committed (large raw artifact). By
default the script downloads it to a cache path and reuses it; pass an existing
file with ``--json-path`` to skip the download.

Usage:
    python scripts/backfill_doc_types.py                 # download + backfill
    python scripts/backfill_doc_types.py --json-path X   # use a local export
    python scripts/backfill_doc_types.py --dry-run       # coverage report only
"""

from __future__ import annotations

import argparse
import logging
import sys
import urllib.request
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.indexing.doc_types import DOCUMENTS_JSON_URL, parse_document_types  # noqa: E402
from harness.indexing.property_graph import (  # noqa: E402
    ensure_document_id_index,
    neo4j_store_from_env,
)

log = logging.getLogger("backfill_doc_types")

_DEFAULT_CACHE = _REPO / ".tmp" / "ema_documents_export.json"


def _load_json_text(json_path: Path, *, force_download: bool) -> str:
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


def backfill(
    *, json_path: Path, force_download: bool, batch_size: int = 10000, dry_run: bool = False
) -> None:
    raw = _load_json_text(json_path, force_download=force_download)
    by_id = parse_document_types(raw)
    log.info("parsed %d document types from export", len(by_id))

    store = neo4j_store_from_env()
    graph = store.structured_query(
        "MATCH (d:Document) RETURN d.id AS id, d.source_type AS source_type"
    )
    pdf_ids = {r["id"] for r in graph if r.get("source_type") == "pdf"}
    total = len(graph)

    updates = [{"id": r["id"], "doc_type": by_id[r["id"]]} for r in graph if r["id"] in by_id]
    pdf_matched = sum(1 for u in updates if u["id"] in pdf_ids)
    log.info(
        "joined %d / %d docs (%.1f%%); PDFs %d / %d (%.1f%%)",
        len(updates), total, 100 * len(updates) / total,
        pdf_matched, len(pdf_ids), 100 * pdf_matched / max(len(pdf_ids), 1),
    )

    print(("[dry-run] " if dry_run else "") + "doc_type histogram (top 30):")
    for t, n in Counter(u["doc_type"] or "(empty)" for u in updates).most_common(30):
        print(f"  {t:36s} {n}")
    if dry_run:
        return

    ensure_document_id_index(store)  # per-id MATCH must not label-scan
    for start in range(0, len(updates), batch_size):
        chunk = updates[start : start + batch_size]
        store.structured_query(
            "UNWIND $rows AS r MATCH (d:Document {id: r.id}) SET d.doc_type = r.doc_type",
            param_map={"rows": chunk},
        )
        log.info("backfilled %d / %d", min(start + batch_size, len(updates)), len(updates))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-path", type=Path, default=_DEFAULT_CACHE,
                        help=f"export file (downloaded if absent; default {_DEFAULT_CACHE})")
    parser.add_argument("--force-download", action="store_true",
                        help="re-download even if the cache file exists")
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument("--dry-run", action="store_true",
                        help="parse + report coverage, write nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    backfill(
        json_path=args.json_path,
        force_download=args.force_download,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
