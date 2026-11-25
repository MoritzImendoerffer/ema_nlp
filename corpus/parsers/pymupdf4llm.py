"""pymupdf4llm parser — parses PDF bytes with the pymupdf4llm installed in ``.venv``.

Until 2026-11-25 this module parsed no PDF. It unpickled the ``parsed_pdf.pkl`` holders
that the scraper's repository wrote into the Scrapy cache, which needs the scraper's
classes on the path: outside ``scripts/ingest_parsed_pdfs.py`` every entry failed with
``pickle_load_failed: No module named 'parsers'``, so the pipeline's ``parse-pdfs`` step
wrote nothing usable. :class:`PymuPdf4LlmParser` now opens the PDF bytes itself.

``parse(raw, url, content_type)``: ``raw`` is the PDF as bytes, as a cache entry's
``response_body`` holds it. A body that starts with the gzip magic bytes ``1f 8b`` is
decompressed first (the cache stores some bodies gzip-encoded). The text is
``pymupdf4llm.to_markdown`` with ``use_ocr``, ``header`` and ``footer`` passed
explicitly, and the row's ``meta`` records them with layout mode and the library
versions (decision E, ``docs/pm/decisions/2026-11-25_pdf-ocr.md``). OCR uses the
system's Tesseract, so another machine can give other text.

Rows carry ``parser: pymupdf4llm`` and the installed library version, e.g.
``1.27.2.3``. The legacy rows of the same name carry ``parser_version: legacy``, and
the preference file ranks them first (decisions A and D).

:class:`LegacyPickleReader` is the old pickle reader. It is kept only until TASK-010 of
work unit 27 removes the pickle path to ``parsed_documents`` (decision G).

The CLI walks a Scrapy cache directory and writes one ``ParsedDocument``
per PDF entry via :func:`corpus.sources.parsed_documents.write_parsed_document`.
"""

from __future__ import annotations

import argparse
import ast
import gzip
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

GZIP_MAGIC = b"\x1f\x8b"
# Passed explicitly so that a library default that changes cannot change the text
# unnoticed; recorded in each row's meta (decision E).
PARSE_OPTIONS: dict[str, bool] = {"use_ocr": True, "header": True, "footer": True}
_VERSIONED_PACKAGES = ("pymupdf4llm", "pymupdf", "pymupdf-layout")


def _package_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for pkg in _VERSIONED_PACKAGES:
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "unknown"
    return out


def parse_pdf_bytes(raw: bytes) -> tuple[str, str, dict[str, object]]:
    """Return ``(text, error, meta)`` for the bytes of one PDF. Never raises.

    Checked against the installed pymupdf4llm 1.27.2.3 (``pymupdf4llm/__init__.py``):
    ``to_markdown(*args, **kwargs)`` goes to ``_layout_to_markdown`` when layout mode
    is on, which it is once ``pymupdf.layout`` imports; ``use_ocr``, ``header`` and
    ``footer`` are keyword options there. The library prints progress to standard
    output.
    """
    meta: dict[str, object] = {**PARSE_OPTIONS, "versions": _package_versions(), "gzip": False}
    if not raw:
        return "", "empty_input", meta
    if raw[:2] == GZIP_MAGIC:
        try:
            raw = gzip.decompress(raw)
        except Exception as exc:  # noqa: BLE001 — diagnostics flow through the error
            return "", f"gzip_failed: {exc}", meta
        meta["gzip"] = True
    import pymupdf
    import pymupdf4llm

    meta["layout"] = bool(getattr(pymupdf4llm, "_use_layout", False))
    try:
        doc = pymupdf.open(stream=raw, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        return "", f"pdf_open_failed: {exc}", meta
    try:
        text = pymupdf4llm.to_markdown(doc, **PARSE_OPTIONS)
    except Exception as exc:  # noqa: BLE001
        return "", f"to_markdown_failed: {exc}", meta
    finally:
        doc.close()
    return str(text or ""), "", meta


class PymuPdf4LlmParser:
    """Parse the bytes of a PDF with the installed pymupdf4llm.

    Conforms to the :class:`corpus.parsers.base.Parser` protocol.
    """

    name: str = PARSER_NAME
    version: str = PARSER_VERSION

    def parse(
        self,
        raw: bytes,
        url: str,
        content_type: str = "application/pdf",
    ) -> ParsedDocument:
        text, error, meta = parse_pdf_bytes(raw if isinstance(raw, bytes) else b"")
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


class LegacyPickleReader:
    """The pickle reader of ``parsed_pdf.pkl`` Scrapy-cache entries (until TASK-010).

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

    parser = LegacyPickleReader()  # switched to the byte parser in TASK-010
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
