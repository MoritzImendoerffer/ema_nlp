"""Integration test for the embed_pg ingest pipeline (NARR-008).

Covers three assertions:
  1. A first --limit N run writes >0 chunks
  2. Re-running the same slice writes zero new chunks (ON CONFLICT path)
  3. --force on the same slice deletes the affected chunks, then re-inserts
     the same number of chunks as the fresh run

This script talks to the live MongoDB + Postgres (whatever PG_DSN points at).
Run with:
    python scripts/test_ingest_resume.py [--limit 5]

Exits non-zero on any assertion failure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness.embed_pg import Embedder, ingest_source  # noqa: E402
from harness.pg.conn import close_pool, get_pool  # noqa: E402


def _chunk_count(pool) -> int:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chunks")
            (n,) = cur.fetchone()
    return n


def _doc_count(pool) -> int:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM documents")
            (n,) = cur.fetchone()
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NARR-008 resume/force integration test.")
    parser.add_argument("--limit", type=int, default=5, help="limit to keep the test cheap")
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args(argv)

    pool = get_pool()
    embedder = Embedder()  # reuse across all runs so the model is loaded once

    before_chunks = _chunk_count(pool)
    before_docs = _doc_count(pool)

    # 1) Fresh ingest on the limit-N slice.
    t1 = ingest_source("pdfs", batch_size=args.batch_size, limit=args.limit, embedder=embedder)
    after_first = _chunk_count(pool)
    fresh_written = after_first - before_chunks
    assert fresh_written > 0, f"first run produced zero new chunks (totals={t1})"
    assert t1["docs_kept"] == args.limit, f"expected {args.limit} docs kept, got {t1['docs_kept']}"

    # 2) Resume: same slice, no --force → zero new chunks.
    t2 = ingest_source("pdfs", batch_size=args.batch_size, limit=args.limit, embedder=embedder)
    after_second = _chunk_count(pool)
    assert after_second == after_first, (
        f"resume re-inserted chunks: before={after_first} after={after_second} totals={t2}"
    )

    # 3) Force: deletes + re-inserts. Final count should match fresh run.
    t3 = ingest_source(
        "pdfs", batch_size=args.batch_size, limit=args.limit, force=True, embedder=embedder
    )
    after_force = _chunk_count(pool)
    after_docs = _doc_count(pool)
    assert after_force == after_second, (
        f"--force ended with {after_force} chunks, expected {after_second}"
    )
    # Document UPSERT never removes rows; the document count must monotonically
    # grow (or stay the same) across the three runs.
    assert after_docs >= before_docs, (
        f"document count regressed: before={before_docs} after={after_docs}"
    )

    print(
        f"NARR-008 PASS  fresh_written={fresh_written}  "
        f"resume_delta=0  force_chunks={after_force}  totals_resume={t2}"
    )
    close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(main())
