"""Upsert all parsed_pdf.pkl files from the Scrapy cache into MongoDB parsed_pdfs collection.

Equivalent to calling get_pdfs_from_cache() from ema_scraper, but reimplements the
cache walk with os.walk (Path.walk is Python 3.12+; this project targets 3.11).
"""

from __future__ import annotations

import argparse
import ast
import datetime
import os
import pickle
import sys
from collections.abc import Iterator
from pathlib import Path

from pymongo import MongoClient, UpdateOne
from tqdm import tqdm

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))
from config import MONGO_DB, MONGO_URI  # noqa: E402

# ema_scraper repo must be on sys.path so pickle can resolve parsers.pdf_parser.PdfDocument
_EMA_SCRAPER_REPO = Path("~/github_repos/ema_scraper").expanduser()
if _EMA_SCRAPER_REPO.exists() and str(_EMA_SCRAPER_REPO) not in sys.path:
    sys.path.insert(0, str(_EMA_SCRAPER_REPO))

# Mirror ema_scraper settings.BASE_PATH; can be overridden via EMA_CACHE_PATH env var.
_DEFAULT_CACHE = Path("~/Nextcloud/Datasets/ema_scraper/cache/ema-sitemap").expanduser()
CACHE_PATH = Path(os.getenv("EMA_CACHE_PATH", str(_DEFAULT_CACHE)))
BATCH_SIZE = 500
# MongoDB hard document limit is 16 MB; skip any markdown exceeding this.
MARKDOWN_MAX_BYTES = 14 * 1024 * 1024  # 14 MB (conservative)


def _iter_pdf_cache(cache_path: Path) -> Iterator[tuple[Path, str]]:
    """Yield (cache_dir, url) for every PDF entry found in the Scrapy cache."""
    for root_str, _dirs, files in os.walk(cache_path):
        if "meta" not in files:
            continue
        root = Path(root_str)
        try:
            with open(root / "meta") as f:
                meta = ast.literal_eval(f.read())
        except Exception:
            continue
        url: str = meta.get("url", "")
        if url.endswith(".pdf"):
            yield root, url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upsert parsed_pdf.pkl files into MongoDB parsed_pdfs collection"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Count pkl files found; no DB writes"
    )
    parser.add_argument("--limit", type=int, default=None, help="Process at most N entries")
    args = parser.parse_args()

    print(f"Scanning {CACHE_PATH} …")
    all_entries: list[tuple[Path, str]] = list(_iter_pdf_cache(CACHE_PATH))
    print(f"Found {len(all_entries)} PDF cache entries")

    if args.limit is not None:
        all_entries = all_entries[: args.limit]

    if args.dry_run:
        pkl_count = sum(1 for p, _ in all_entries if (p / "parsed_pdf.pkl").exists())
        print(
            f"Dry run: {pkl_count} parsed_pdf.pkl files present"
            f" (of {len(all_entries)} scanned)"
        )
        return

    client: MongoClient = MongoClient(MONGO_URI)
    col = client[MONGO_DB]["parsed_pdfs"]

    ops: list[UpdateOne] = []
    ingested = errors = skipped = 0
    now = datetime.datetime.now(datetime.UTC).isoformat()

    for cache_dir, url in tqdm(all_entries, desc="Ingesting", unit="pdf"):
        pkl = cache_dir / "parsed_pdf.pkl"
        if not pkl.exists():
            skipped += 1
            continue
        try:
            with open(pkl, "rb") as f:
                doc = pickle.load(f)
            markdown: str = doc.markdown
            if len(markdown.encode()) > MARKDOWN_MAX_BYTES:
                tqdm.write(f"SKIP {pkl}: markdown {len(markdown)} chars exceeds limit")
                skipped += 1
                continue
            ops.append(
                UpdateOne(
                    {"_id": url},
                    {
                        "$set": {
                            "markdown": markdown,
                            "parsed_with": getattr(doc, "parsed_with", "unknown"),
                            "error": getattr(doc, "error", ""),
                            "cache_path": str(cache_dir),
                            "ingested_at": now,
                        }
                    },
                    upsert=True,
                )
            )
            ingested += 1
        except Exception as exc:
            tqdm.write(f"ERROR {pkl}: {exc}")
            errors += 1

        if len(ops) >= BATCH_SIZE:
            col.bulk_write(ops)
            ops = []

    if ops:
        col.bulk_write(ops)

    client.close()
    print(
        f"\nDone — total={len(all_entries)}"
        f"  ingested={ingested}"
        f"  errors={errors}"
        f"  skipped={skipped}"
    )


if __name__ == "__main__":
    main()
