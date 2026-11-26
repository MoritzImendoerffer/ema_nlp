#!/usr/bin/env python
"""Parse a ranked list of PDFs with the ``docling`` parser (backlog row 17, work unit 28).

Runs only in the parse environment (``make parse-env``), never in .venv. The loop is
``corpus/parsers/docling_batch.py``; its docstring says what a batch does.

Usage::

    PY=$(.venv/bin/python -c 'import config; print(config.DOCLING_ENV)')/bin/python
    $PY scripts/parse_pdfs_docling.py <list.jsonl> --budget-pages 8400

    touch "$EMA_PARSED_ROOT/STOP"   # stop between documents, e.g. before a graph build

The list is JSONL with ``url`` and ``cache_path`` per line, as
``scripts/rank_pdfs_by_tables.py`` writes it. Files go to ``config.PARSED_ROOT``; the Mongo
row is written only with ``--write-mongo``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from corpus.parsers.docling_batch import BatchSettings, load_items, run_batch  # noqa: E402


def power_limit() -> str:
    """The GPU's power limit as nvidia-smi reports it, or why it is unknown."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=power.limit", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10, check=True)
        return out.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"unknown ({type(exc).__name__})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("list", type=Path, help="JSONL with url and cache_path per line")
    ap.add_argument("--budget-pages", type=int, required=True, help="stop before the next document would exceed it")
    ap.add_argument("--root", type=Path, default=config.PARSED_ROOT)
    ap.add_argument("--docs-per-worker", type=int, default=50, help="replace the worker after this many documents")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--range-pages", type=int, default=100, help="parse a longer PDF in ranges of this many pages")
    ap.add_argument("--pause-every-docs", type=int, default=20)
    ap.add_argument("--pause-seconds", type=float, default=60.0)
    ap.add_argument("--stop-file", type=Path, default=None, help="default: <root>/STOP")
    ap.add_argument("--write-mongo", action="store_true", help="also write the parsed_documents row (off in batch 0)")
    args = ap.parse_args(argv)

    args.root.mkdir(parents=True, exist_ok=True)
    log_path = args.root / "batch_logs" / f"{args.list.stem}_{datetime.now():%Y%m%dT%H%M%S}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"GPU power limit: {power_limit()}; log: {log_path}", flush=True)
    settings = BatchSettings(root=args.root, budget_pages=args.budget_pages, docs_per_worker=args.docs_per_worker,
                             workers=args.workers, range_pages=args.range_pages,
                             pause_every=args.pause_every_docs, pause_seconds=args.pause_seconds,
                             stop_file=args.stop_file, write_mongo=args.write_mongo, log_path=log_path,
                             echo=lambda line: print(line, flush=True))
    summary = run_batch(load_items(args.list), settings)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
