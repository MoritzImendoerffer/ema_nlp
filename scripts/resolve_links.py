"""Fill ``links.tgt_doc_id`` by matching unresolved rows against ``documents``.

Two resolution passes:

    hyperlink         tgt_url == documents.source_url
    reference_number  tgt_url == documents.reference_number

Both UPDATE queries restrict to rows where ``tgt_doc_id IS NULL``, so re-running
the script is a no-op once everything resolvable has been resolved.

Expected hyperlink resolution rate on a full ingest is **≥ 30 %** — many of the
hyperlink targets point off-site (FDA, ICH, third-party guidance) and won't be
matchable against documents already in pgvector. Reference-number resolution
should be higher for documents that mention their own committee codes.

Usage::

    python scripts/resolve_links.py                # apply both passes
    python scripts/resolve_links.py --dry-run      # report counts only (no writes)
    python scripts/resolve_links.py --sample 20    # show 20 sample unresolved entries
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness.pg import queries as Q  # noqa: E402
from harness.pg.conn import close_pool, get_pool  # noqa: E402

_log = logging.getLogger(__name__)


def _counts(cur) -> dict[str, int]:
    cur.execute("SELECT link_type, tgt_doc_id IS NULL AS pending, COUNT(*) FROM links GROUP BY 1, 2")
    rows = cur.fetchall()
    out = {
        "hyperlink_total": 0,
        "hyperlink_unresolved": 0,
        "reference_number_total": 0,
        "reference_number_unresolved": 0,
        "see_qa_total": 0,
        "see_qa_unresolved": 0,
    }
    for link_type, pending, n in rows:
        key_total = f"{link_type}_total"
        key_pending = f"{link_type}_unresolved"
        if key_total in out:
            out[key_total] += n
            if pending:
                out[key_pending] += n
    return out


def _print_counts(label: str, counts: dict[str, int]) -> None:
    print(f"-- {label}")
    for link_type in ("hyperlink", "reference_number", "see_qa"):
        total = counts.get(f"{link_type}_total", 0)
        pending = counts.get(f"{link_type}_unresolved", 0)
        resolved = total - pending
        pct = (resolved / total * 100) if total else 0.0
        print(f"   {link_type:>17}: total={total:6d}  resolved={resolved:6d}  pending={pending:6d}  rate={pct:5.1f}%")


def _sample_unresolved(cur, limit: int) -> list[tuple[str, str, int]]:
    cur.execute(Q.UNRESOLVED_LINKS_SAMPLE, {"limit": limit})
    return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Resolve links.tgt_doc_id against documents.")
    p.add_argument("--dry-run", action="store_true", help="report counts only; do not UPDATE")
    p.add_argument("--sample", type=int, default=10, help="how many unresolved entries to print")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    pool = get_pool()
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                before = _counts(cur)
            _print_counts("before", before)

            if not args.dry_run:
                with conn.cursor() as cur:
                    cur.execute(Q.RESOLVE_LINKS_BY_URL)
                    n_url = cur.rowcount
                    cur.execute(Q.RESOLVE_LINKS_BY_REFERENCE)
                    n_ref = cur.rowcount
                conn.commit()
                _log.info("resolved %d hyperlinks by URL, %d by reference number", n_url, n_ref)

            with conn.cursor() as cur:
                after = _counts(cur)
            _print_counts("after", after)

            if args.sample > 0:
                with conn.cursor() as cur:
                    sample = _sample_unresolved(cur, args.sample)
                print(f"-- unresolved sample (top {len(sample)} by count)")
                for link_type, tgt_url, n in sample:
                    truncated = tgt_url if len(tgt_url) <= 100 else tgt_url[:97] + "..."
                    print(f"   [{link_type:>17}] (n={n}) {truncated}")
    finally:
        close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(main())
