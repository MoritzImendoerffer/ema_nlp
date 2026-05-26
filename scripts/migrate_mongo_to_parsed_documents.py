"""Backfill `parsed_pdfs` + `web_items` rows into `parsed_documents` (MIGR-012).

Two-step migration that complements MIGR-008's synthetic legacy reader:

  * synthetic_legacy_reader.iter_parsed_documents_from_legacy → on-the-fly
    bridge so sync() can run against today's data with no backfill.
  * this script → one-shot copy of those bridged rows into the canonical
    `parsed_documents` collection so the bridge can be retired (MIGR-013).

Idempotent via the compound unique index on (url, parser, parser_version)
in parsed_documents — re-running the script with the same source data
upserts the same rows without growing the collection.

Stat lines printed at the end (and returned from main()) match what
MIGR-013's HISTORY entry needs:

    read     — rows pulled from the legacy collections
    written  — ParsedDocument upserts (1-to-1 with read after filters)
    skipped  — error rows or landing pages excluded by default
    errors   — exceptions during write (rare)

CLI:
    python scripts/migrate_mongo_to_parsed_documents.py \\
        [--source pdfs|html|both] [--limit N] [--batch-size N] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pymongo import MongoClient  # noqa: E402

from config import MONGO_URI  # noqa: E402
from corpus.sources.parsed_documents import (  # noqa: E402
    bootstrap_indexes,
    write_parsed_document,
)
from corpus.sources.synthetic_legacy_reader import (  # noqa: E402
    iter_parsed_documents_from_legacy,
)

_log = logging.getLogger(__name__)

SOURCE_CHOICES = ("pdfs", "html", "both")


def run_migration(
    *,
    source: str = "both",
    limit: int | None = None,
    dry_run: bool = False,
    client: MongoClient | None = None,
) -> dict[str, int]:
    """Drive the backfill. Returns a counts dict (also printed on the CLI)."""
    content_types: list[str]
    if source == "pdfs":
        content_types = ["application/pdf"]
    elif source == "html":
        content_types = ["text/html"]
    elif source == "both":
        content_types = ["application/pdf", "text/html"]
    else:
        raise ValueError(f"--source must be one of {SOURCE_CHOICES}, got {source!r}")

    owned = client is None
    c: MongoClient = MongoClient(MONGO_URI) if owned else client  # type: ignore[assignment]
    counts = {"read": 0, "written": 0, "skipped": 0, "errors": 0}
    try:
        if not dry_run:
            bootstrap_indexes(client=c)
        for parsed in iter_parsed_documents_from_legacy(
            client=c,
            content_types=content_types,
        ):
            counts["read"] += 1
            if limit and counts["read"] > limit:
                break
            if parsed.error:
                # Should be rare: include_errors=False filters most out, but
                # we double-check here so the script never mis-attributes.
                counts["skipped"] += 1
                continue
            if dry_run:
                counts["written"] += 1
                continue
            try:
                write_parsed_document(parsed, client=c)
                counts["written"] += 1
            except Exception as exc:  # noqa: BLE001
                _log.warning("write failed for %s: %s", parsed.url, exc)
                counts["errors"] += 1
    finally:
        if owned:
            c.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    p.add_argument("--source", choices=SOURCE_CHOICES, default="both")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Reserved for future per-batch bulk_write tuning; currently unused.",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    counts = run_migration(source=args.source, limit=args.limit, dry_run=args.dry_run)
    print(
        f"\nDone — source={args.source} read={counts['read']}"
        f" written={counts['written']}"
        f" skipped={counts['skipped']}"
        f" errors={counts['errors']}"
        f"  (dry_run={args.dry_run})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
