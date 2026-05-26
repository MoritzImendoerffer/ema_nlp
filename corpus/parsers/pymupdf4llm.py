"""pymupdf4llm parser — wraps ``parsed_pdf.pkl`` files from the Scrapy cache.

The upstream ``ema_scraper`` pipeline parses PDFs with pymupdf4llm and
pickles a small holder object (``PdfDocument`` with ``markdown``, ``error``,
``parsed_with``) per cached URL. This parser unpickles such a holder and
emits a ``ParsedDocument`` for the Mongo ``parsed_documents`` collection.

``raw`` semantics for ``parse``:
    bytes  — raw pickle bytes (preferred; the CLI reads files and passes
             bytes so the parser stays I/O-free).
    str    — filesystem path to a ``parsed_pdf.pkl`` file (convenience for
             ad-hoc scripts).

The CLI walks a Scrapy cache directory and writes one ``ParsedDocument``
per PDF entry via :func:`corpus.sources.parsed_documents.write_parsed_document`.
"""

from __future__ import annotations

import argparse
import ast
import logging
import os
import pickle
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from pymongo import MongoClient
from tqdm import tqdm

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import MONGO_URI  # noqa: E402
from corpus.parsers.base import ParsedDocument  # noqa: E402
from corpus.sources.parsed_documents import (  # noqa: E402
    bootstrap_indexes,
    write_parsed_document,
)

_log = logging.getLogger(__name__)

PARSER_NAME = "pymupdf4llm"


def _resolve_version() -> str:
    try:
        return version("pymupdf4llm")
    except PackageNotFoundError:
        return "unknown"


PARSER_VERSION = _resolve_version()


class PymuPdf4LlmParser:
    """Parser wrapping ``parsed_pdf.pkl`` Scrapy-cache entries.

    Conforms to the :class:`corpus.parsers.base.Parser` protocol.
    """

    name: str = PARSER_NAME
    version: str = PARSER_VERSION

    def parse(
        self,
        raw: bytes | str,
        url: str,
        content_type: str = "application/pdf",
    ) -> ParsedDocument:
        text, error, parsed_with = _load_pickle(raw)
        meta: dict[str, object] = {}
        if parsed_with:
            meta["parsed_with"] = parsed_with
        if isinstance(raw, str):
            meta["cache_path"] = raw
        return ParsedDocument(
            url=url,
            parser=self.name,
            parser_version=self.version,
            parsed_at=datetime.now(UTC),
            content_type=content_type or "application/pdf",
            text=text,
            text_format="markdown",
            error=error,
            meta=meta,
        )


def _load_pickle(raw: bytes | str) -> tuple[str, str, str]:
    """Return (text, error, parsed_with). Never raises."""
    if raw is None or (isinstance(raw, (bytes, str)) and not raw):
        return ("", "empty_input", "")
    try:
        if isinstance(raw, bytes):
            doc = pickle.loads(raw)
        else:
            with open(raw, "rb") as f:
                doc = pickle.load(f)
    except Exception as exc:  # noqa: BLE001 — diagnostics flow through .error
        return ("", f"pickle_load_failed: {exc}", "")
    text = getattr(doc, "markdown", "") or ""
    inner_error = getattr(doc, "error", "") or ""
    parsed_with = getattr(doc, "parsed_with", "") or ""
    return (text, inner_error, parsed_with)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _iter_pdf_cache(cache_path: Path) -> Iterator[tuple[Path, str]]:
    """Yield (cache_dir, url) for every PDF entry found in a Scrapy cache."""
    for root_str, _dirs, files in os.walk(cache_path):
        if "meta" not in files:
            continue
        root = Path(root_str)
        try:
            with open(root / "meta") as f:
                meta = ast.literal_eval(f.read())
        except Exception:  # noqa: BLE001
            continue
        url: str = meta.get("url", "")
        if url.endswith(".pdf"):
            yield root, url


def _cli(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(
        description="Walk a Scrapy cache, parse each parsed_pdf.pkl, and "
        "write the result into the Mongo `parsed_documents` collection."
    )
    cli.add_argument(
        "--cache",
        type=Path,
        required=True,
        help="Scrapy cache root (e.g. ~/Nextcloud/Datasets/ema_scraper/cache/ema-sitemap)",
    )
    cli.add_argument("--limit", type=int, default=None, help="Process at most N entries")
    cli.add_argument(
        "--url",
        type=str,
        default=None,
        help="Restrict to a single URL (still requires --cache to find its entry)",
    )
    cli.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the parser but don't write to Mongo (counts only)",
    )
    args = cli.parse_args(argv)

    parser = PymuPdf4LlmParser()
    print(f"Scanning {args.cache} …")
    entries: list[tuple[Path, str]] = []
    for cache_dir, url in _iter_pdf_cache(args.cache):
        if args.url and url != args.url:
            continue
        entries.append((cache_dir, url))
        if args.limit and len(entries) >= args.limit:
            break
    print(f"Found {len(entries)} PDF cache entries to parse")

    if args.dry_run:
        with_pkl = sum(1 for d, _ in entries if (d / "parsed_pdf.pkl").exists())
        print(f"Dry run: {with_pkl} would be parsed (of {len(entries)})")
        return 0

    client: MongoClient = MongoClient(MONGO_URI)
    try:
        bootstrap_indexes(client=client)
        written = errors = skipped = 0
        for cache_dir, url in tqdm(entries, desc="Parsing", unit="pdf"):
            pkl = cache_dir / "parsed_pdf.pkl"
            if not pkl.exists():
                skipped += 1
                continue
            with open(pkl, "rb") as f:
                raw_bytes = f.read()
            doc = parser.parse(raw_bytes, url=url, content_type="application/pdf")
            if doc.error:
                errors += 1
                _log.warning("parser error for %s: %s", url, doc.error)
            try:
                write_parsed_document(doc, client=client)
                written += 1
            except Exception as exc:  # noqa: BLE001
                _log.error("write failed for %s: %s", url, exc)
                errors += 1
        print(
            f"\nDone — entries={len(entries)} written={written}"
            f" errors={errors} skipped={skipped}"
        )
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
