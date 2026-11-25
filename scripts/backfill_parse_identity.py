#!/usr/bin/env python
"""Stamp the parse identity on the graph documents that do not record one yet.

Since 2026-11-25 each ``:Document`` records the parse its chunks were built from:
``parser``, ``parser_version`` and ``text_sha256`` (work unit 27). The 79,882 documents
built before that record none. This script sets the three properties from the row that
the build used before 2026-11-25: the first clean row of ``parsed_documents`` that the
URL-sorted cursor yields (the "old-rule" row). It never writes a chunk, an edge or a
Mongo row, and it touches only documents without ``text_sha256``, so it can stop and
resume.

Why the old-rule row: the graph's chunks were built from it. The exploration of work
unit 27 rebuilt the chunks of 80 sampled documents from today's rows and got exactly the
chunk ids in the graph (80 of 80). ``--verify N`` repeats that check on N stamped
documents.

The script also counts the URLs whose old-rule row differs from the row the new
selection picks (``harness/configs/parser_preference.yaml``). Each such document will
be compared, stamped or replaced by the next build.

Usage::

    # read-only: count and time, write nothing
    python scripts/backfill_parse_identity.py --dry-run --limit 1000

    # stamp every unstamped document, then check 100 of them
    python scripts/backfill_parse_identity.py --verify 100

Way back: ``MATCH (d:Document) CALL { WITH d REMOVE d.parser, d.parser_version,
d.text_sha256 } IN TRANSACTIONS OF 10000 ROWS``. No document held these properties
before work unit 27.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.indexing.chunking import doc_id_for  # noqa: E402
from harness.indexing.graph_ops import DOC_BATCH, CorpusGraph  # noqa: E402
from harness.indexing.ingest import (  # noqa: E402
    PARSED_COLLECTION,
    build_ingested_doc,
    iter_source_groups,
    text_sha256,
)
from harness.indexing.profiles import ChunkingConfig, ScopeConfig  # noqa: E402

_log = logging.getLogger("backfill_parse_identity")


@dataclass
class BackfillReport:
    graph_documents: int = 0
    unstamped_before: int = 0
    urls_read: int = 0
    stamped: int = 0
    old_rule_differs: int = 0
    seconds: float = 0.0

    def lines(self, *, dry_run: bool) -> list[str]:
        verb = "would stamp" if dry_run else "stamped"
        rate = self.urls_read / self.seconds if self.seconds else 0.0
        return [
            f"graph documents: {self.graph_documents}, without text_sha256: {self.unstamped_before}",
            f"rows read: {self.urls_read} URLs in {self.seconds:.1f} s ({rate:.0f} URLs/s)",
            f"{verb}: {self.stamped}",
            f"old-rule row differs from the selected row: {self.old_rule_differs}",
        ]


def _identity(row: dict[str, Any]) -> tuple[Any, Any]:
    return row.get("parser"), row.get("parser_version")


def backfill(graph: Any, client: Any, *, dry_run: bool = False, limit: int | None = None) -> BackfillReport:
    """Stamp each unstamped graph document from its old-rule row.

    ``limit`` stops after that many unstamped documents were handled (a timing sample).
    """
    t0 = time.time()
    report = BackfillReport()
    states = graph.document_states()
    report.graph_documents = len(states)
    unstamped = {doc_id for doc_id, s in states.items() if not s.stamped}
    report.unstamped_before = len(unstamped)
    pending: list[dict[str, Any]] = []
    for choice in iter_source_groups(ScopeConfig(), client=client):
        report.urls_read += 1
        old = choice.old_rule
        doc_id = doc_id_for(old["url"])
        if doc_id not in unstamped:
            continue
        if _identity(old) != _identity(choice.selected):
            report.old_rule_differs += 1
        pending.append({
            "id": doc_id, "parser": old.get("parser"), "parser_version": old.get("parser_version"),
            "text_sha256": text_sha256(old.get("text", "") or ""),
        })
        report.stamped += 1
        if len(pending) >= DOC_BATCH:
            if not dry_run:
                graph.stamp_parse_identity(pending)
            pending = []
        if limit and report.stamped >= limit:
            break
    if pending and not dry_run:
        graph.stamp_parse_identity(pending)
    report.seconds = time.time() - t0
    return report


def verify(
    graph: Any, client: Any, chunking: ChunkingConfig, n: int, *, seed: int = 0
) -> tuple[int, int, list[str]]:
    """Rebuild the chunks of ``n`` stamped documents from their stamped row and compare.

    Returns ``(equal, checked, unequal_doc_ids)``. A document is equal when the chunk
    ids, texts and leaf flags that ``build_ingested_doc`` gives for the row named by its
    stamp are exactly the ones the graph holds.
    """
    from config import MONGO_DB

    stamped = sorted(
        (s for s in graph.document_states().values() if s.stamped and s.has_chunks),
        key=lambda s: s.doc_id,
    )
    sample = random.Random(seed).sample(stamped, min(n, len(stamped)))
    col = client[MONGO_DB][PARSED_COLLECTION]
    equal = 0
    unequal: list[str] = []
    for s in sample:
        row = col.find_one({"url": s.source_url, "parser": s.parser, "parser_version": s.parser_version})
        if row is None or text_sha256(row.get("text", "") or "") != s.text_sha256:
            unequal.append(s.doc_id)
            continue
        doc = build_ingested_doc(row, chunking=chunking, html_lookup=lambda _u: None)
        want = sorted((c.node_id, c.text, bool(c.metadata.get("is_leaf"))) for c in doc.chunk_nodes)
        have = sorted((c["id"], c["text"], c["is_leaf"]) for c in graph.document_chunks(s.doc_id))
        if want == have:
            equal += 1
        else:
            unequal.append(s.doc_id)
    return equal, len(sample), unequal


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="read and count; write nothing")
    ap.add_argument("--limit", type=int, default=None, help="stop after N unstamped documents")
    ap.add_argument("--verify", type=int, default=0, metavar="N",
                    help="afterwards, rebuild the chunks of N stamped documents and compare")
    ap.add_argument("--profile", default=None, help="index profile for --verify's chunking")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from pymongo import MongoClient

    from config import MONGO_URI
    from harness.indexing import load_index_profile
    from harness.indexing.property_graph import neo4j_store_from_env

    graph = CorpusGraph(neo4j_store_from_env())
    client: MongoClient = MongoClient(MONGO_URI)
    try:
        report = backfill(graph, client, dry_run=args.dry_run, limit=args.limit)
        for line in report.lines(dry_run=args.dry_run):
            print(line)
        if args.verify:
            chunking = load_index_profile(args.profile).index.chunking
            equal, checked, unequal = verify(graph, client, chunking, args.verify)
            print(f"verify: {equal} of {checked} equal")
            for doc_id in unequal[:20]:
                print(f"  unequal: {doc_id}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
