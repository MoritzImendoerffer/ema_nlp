#!/usr/bin/env python
"""Rank the PDFs for Docling parsing by their complex tables (backlog row 17, work unit 28).

The order is the proposal's (``docs/next/pdf_parsing_docling.md``, "The batches"):

1. Documents with complex tables, by descending score. The score is the number of cells
   in the document's complex tables, read from today's text (the legacy ``pymupdf4llm``
   row). A table is a run of lines starting with ``|`` that holds a separator line
   (``|---|``). It is complex when it has 8 or more columns, 20 or more rows, or ragged
   rows (rows with different cell counts).
2. Documents with pages without text (under 50 characters on the page), most such pages
   first. OCR does the work there.
3. All others.

A PDF without a legacy row is not ranked: the proposal ranks it once it has a text.

The script only reads: MongoDB ``parsed_documents`` and the Scrapy cache. It writes one
JSONL file under ``config.RESULTS_DIR``. Counting the pages of about 58,000 PDFs took
567 s with 4 processes in the exploration.

Usage::

    .venv/bin/python scripts/rank_pdfs_by_tables.py               # all legacy rows
    .venv/bin/python scripts/rank_pdfs_by_tables.py --limit 500   # a sample
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
from collections.abc import Iterable, Iterator
from datetime import date
from multiprocessing import Pool
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402

LEGACY_QUERY = {"parser": "pymupdf4llm", "parser_version": "legacy", "error": ""}
SEPARATOR = re.compile(r"^\|\s*:?-{3,}")
WIDE_COLS = 8
LONG_ROWS = 20
NO_TEXT_CHARS = 50
GZIP_MAGIC = b"\x1f\x8b"


def markdown_tables(text: str) -> list[dict[str, Any]]:
    """The Markdown tables in ``text``: columns, rows, raggedness and cells of each."""
    blocks: list[list[str]] = []
    block: list[str] = []
    for line in text.split("\n"):
        if line.lstrip().startswith("|"):
            block.append(line.strip())
            continue
        if block:
            blocks.append(block)
        block = []
    if block:
        blocks.append(block)
    tables = []
    for b in blocks:
        if not any(SEPARATOR.match(x) for x in b):
            continue  # pipes without a separator line are not a table
        counts = [x.count("|") - 1 for x in b if not SEPARATOR.match(x)]
        if counts:
            tables.append({"cols": max(counts), "rows": len(counts), "ragged": len(set(counts)) > 1,
                           "cells": sum(counts)})
    return tables


def is_complex(table: dict[str, Any]) -> bool:
    return table["cols"] >= WIDE_COLS or table["rows"] >= LONG_ROWS or table["ragged"]


def table_score(text: str) -> dict[str, int]:
    """``score`` = cells in complex tables; also the number of tables and of complex ones."""
    tables = markdown_tables(text)
    complex_tables = [t for t in tables if is_complex(t)]
    return {"score": sum(t["cells"] for t in complex_tables), "tables": len(tables),
            "complex_tables": len(complex_tables)}


def cache_facts(cache_path: str | None) -> dict[str, Any]:
    """Pages, pages without text and gzip flag of one cached PDF. Never raises."""
    if not cache_path:
        return {"pages": None, "pages_without_text": None, "gzip": None, "cache_error": "no cache_path"}
    try:
        import pymupdf

        raw = (Path(cache_path) / "response_body").read_bytes()
        packed = raw[:2] == GZIP_MAGIC
        if packed:
            raw = gzip.decompress(raw)
        with pymupdf.open(stream=raw, filetype="pdf") as doc:
            low = sum(1 for page in doc if len(page.get_text("text").strip()) < NO_TEXT_CHARS)
            return {"pages": doc.page_count, "pages_without_text": low, "gzip": packed, "cache_error": ""}
    except Exception as exc:  # noqa: BLE001 — one bad file must not stop the ranking
        return {"pages": None, "pages_without_text": None, "gzip": None,
                "cache_error": f"{type(exc).__name__}: {exc}"[:200]}


def _facts(item: tuple[str, str | None]) -> tuple[str, dict[str, Any]]:
    url, cache_path = item
    return url, cache_facts(cache_path)


def tier(rec: dict[str, Any]) -> int:
    if rec["score"] > 0:
        return 1
    if rec.get("pages_without_text"):
        return 2
    return 3


def rank(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order the records: tier 1 by score, tier 2 by pages without text, tier 3 by URL."""
    def key(rec: dict[str, Any]) -> tuple[Any, ...]:
        t = tier(rec)
        if t == 1:
            return (1, -rec["score"], rec["url"])
        if t == 2:
            return (2, -rec["pages_without_text"], rec["url"])
        return (3, 0, rec["url"])

    out = sorted(records, key=key)
    for i, rec in enumerate(out, 1):
        rec["rank"] = i
        rec["tier"] = tier(rec)
    return out


def scored_rows(rows: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for r in rows:
        yield {"url": r["url"], **table_score(r.get("text") or ""),
               "cache_path": (r.get("meta") or {}).get("cache_path")}


def build_ranking(rows: Iterable[dict[str, Any]], workers: int = 4) -> list[dict[str, Any]]:
    """Score the rows, add the cache facts, rank. ``rows`` are legacy ``parsed_documents`` rows."""
    records = {r["url"]: r for r in scored_rows(rows)}
    items = [(u, r["cache_path"]) for u, r in records.items()]
    if workers > 1:
        with Pool(workers) as pool:
            facts = dict(pool.imap_unordered(_facts, items, chunksize=50))
    else:
        facts = dict(map(_facts, items))
    for url, rec in records.items():
        rec.update(facts[url])
    return rank(records.values())


def summary(ranked: list[dict[str, Any]]) -> dict[str, Any]:
    return {"legacy_rows": len(ranked),
            "score_above_0": sum(1 for r in ranked if r["tier"] == 1),
            "pages_without_text_tier": sum(1 for r in ranked if r["tier"] == 2),
            "others": sum(1 for r in ranked if r["tier"] == 3),
            "cache_errors": sum(1 for r in ranked if r["cache_error"]),
            "pages": sum(r["pages"] or 0 for r in ranked)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=None,
                    help="default: RESULTS_DIR/docling/ranking_<date>.jsonl")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="rank only the first N legacy rows (a sample)")
    args = ap.parse_args(argv)

    from pymongo import MongoClient

    out = args.out or config.RESULTS_DIR / "docling" / f"ranking_{date.today().isoformat()}.jsonl"
    t0 = time.time()
    col = MongoClient(config.MONGO_URI)[config.MONGO_DB]["parsed_documents"]
    cursor = col.find(LEGACY_QUERY, {"url": 1, "text": 1, "meta.cache_path": 1}, no_cursor_timeout=True)
    if args.limit:
        cursor = cursor.limit(args.limit)
    try:
        ranked = build_ranking(cursor, workers=args.workers)
    finally:
        cursor.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    with open(tmp, "w", encoding="utf-8") as fh:
        for rec in ranked:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(out)
    print(json.dumps({**summary(ranked), "out": str(out), "seconds": round(time.time() - t0)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
