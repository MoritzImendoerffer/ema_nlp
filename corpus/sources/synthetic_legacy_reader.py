"""Bridge legacy `parsed_pdfs` + `web_items` Mongo rows into a stream of
:class:`ParsedDocument` instances.

This is the transition fixture (MIGR-008) that lets the refactored
:func:`harness.embed_pg.sync` run against today's data **without** a
one-shot backfill. The backfill (MIGR-012) writes the same rows into the
new ``parsed_documents`` collection; once that lands and MIGR-013 runs,
this reader becomes dead code and is removed.

Two row shapes are handled:

* ``parsed_pdfs``: ``{_id: url, markdown: str, error: str, cache_path,
  ingested_at}`` → ``ParsedDocument(parser='pymupdf4llm',
  parser_version='legacy', text_format='markdown',
  content_type='application/pdf')``.
* ``web_items`` with ``content_type='text/html'``: ``{url: [str],
  html_raw: [str]}`` → runs :class:`TrafilaturaParser` to produce a
  ``ParsedDocument(parser='trafilatura', parser_version='legacy', …)``.
  Landing pages (``error == 'landing_page_below_min_chars'``) are
  filtered out unless ``include_errors=True``.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pymongo import MongoClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import MONGO_DB, MONGO_URI  # noqa: E402
from corpus.parsers.base import ParsedDocument  # noqa: E402
from corpus.parsers.trafilatura import (  # noqa: E402
    LANDING_PAGE_ERROR,
    TrafilaturaParser,
)

_log = logging.getLogger(__name__)

LEGACY_VERSION = "legacy"


def _unwrap(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _pdf_row_to_parsed_doc(row: dict[str, Any]) -> ParsedDocument | None:
    url = row.get("_id")
    if not isinstance(url, str) or not url:
        return None
    markdown = row.get("markdown") or ""
    error = row.get("error") or ""
    meta: dict[str, Any] = {}
    if row.get("cache_path"):
        meta["cache_path"] = row["cache_path"]
    if row.get("ingested_at"):
        meta["ingested_at"] = row["ingested_at"]
    # ParsedDocument requires non-empty text OR an error string. Legacy rows
    # with empty markdown + empty error are unusable — skip.
    if not markdown and not error:
        return None
    return ParsedDocument(
        url=url,
        parser="pymupdf4llm",
        parser_version=LEGACY_VERSION,
        parsed_at=datetime.now(UTC),
        content_type="application/pdf",
        text=markdown,
        text_format="markdown",
        error=error,
        meta=meta,
    )


def _html_row_to_parsed_doc(
    row: dict[str, Any], parser: TrafilaturaParser
) -> ParsedDocument | None:
    url = _unwrap(row.get("url") or row.get("_id"))
    html = _unwrap(row.get("html_raw"))
    if not isinstance(url, str) or not isinstance(html, str):
        return None
    doc = parser.parse(html, url=url, content_type="text/html")
    # Override parser_version: the synthetic reader represents the
    # legacy parse step regardless of the installed trafilatura version.
    return ParsedDocument(
        url=doc.url,
        parser=doc.parser,
        parser_version=LEGACY_VERSION,
        parsed_at=doc.parsed_at,
        content_type=doc.content_type,
        text=doc.text,
        text_format=doc.text_format,
        error=doc.error,
        meta=doc.meta,
    )


def iter_parsed_documents_from_legacy(
    *,
    client: MongoClient | None = None,
    content_types: list[str] | None = None,
    include_errors: bool = False,
) -> Iterator[ParsedDocument]:
    """Stream ParsedDocument instances built from legacy Mongo collections.

    Args:
        client          — optional MongoClient (defaults to MONGO_URI).
        content_types   — restrict to a subset of
                          ``['application/pdf','text/html']``. Default: both.
        include_errors  — when False (default), rows whose ParsedDocument
                          carries an error are dropped; when True they're
                          emitted (useful for diagnostic tooling).
    """
    content_types = content_types or ["application/pdf", "text/html"]
    owned = client is None
    c: MongoClient = MongoClient(MONGO_URI) if owned else client  # type: ignore[assignment]
    try:
        if "application/pdf" in content_types:
            yield from _iter_pdfs(c, include_errors=include_errors)
        if "text/html" in content_types:
            yield from _iter_html(c, include_errors=include_errors)
    finally:
        if owned:
            c.close()


def _iter_pdfs(client: MongoClient, *, include_errors: bool) -> Iterator[ParsedDocument]:
    col = client[MONGO_DB]["parsed_pdfs"]
    for row in col.find({}):
        doc = _pdf_row_to_parsed_doc(row)
        if doc is None:
            continue
        if doc.error and not include_errors:
            continue
        yield doc


def _iter_html(client: MongoClient, *, include_errors: bool) -> Iterator[ParsedDocument]:
    col = client[MONGO_DB]["web_items"]
    parser = TrafilaturaParser()
    for row in col.find({"content_type": "text/html"}):
        doc = _html_row_to_parsed_doc(row, parser)
        if doc is None:
            continue
        if doc.error and not include_errors:
            if doc.error != LANDING_PAGE_ERROR:
                _log.warning("html row error for %s: %s", doc.url, doc.error)
            continue
        yield doc
