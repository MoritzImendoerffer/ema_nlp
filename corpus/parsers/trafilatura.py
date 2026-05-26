"""Trafilatura parser — converts raw HTML into markdown for the corpus.

Wraps :func:`trafilatura.extract` with the same kwargs the legacy
``corpus/ingestion/html_normaliser.normalise_html`` uses
(``output_format='markdown'``, ``include_links=True``, ``include_tables=True``,
``with_metadata=False``, ``favor_recall=True``).

``parse`` semantics:
    raw           — HTML bytes or str. ``bytes`` is decoded as utf-8 with
                    ``errors='replace'`` so HTML pages with mixed encodings
                    don't crash the parser.
    url           — the source URL (used by trafilatura's resolver for
                    relative links and exposed back on the ParsedDocument).
    content_type  — ignored for trafilatura (always treated as text/html);
                    we still echo it back so the writer records ``"text/html"``.

Landing-page guard: when the extracted body is shorter than 200 chars we
return a ``ParsedDocument`` with ``error="landing_page_below_min_chars"``
and empty text (matches the legacy behaviour).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import trafilatura
from pymongo import MongoClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import MONGO_DB, MONGO_URI  # noqa: E402
from corpus.parsers.base import ParsedDocument  # noqa: E402
from corpus.sources.parsed_documents import (  # noqa: E402
    bootstrap_indexes,
    write_parsed_document,
)

_log = logging.getLogger(__name__)

PARSER_NAME = "trafilatura"
LANDING_PAGE_ERROR = "landing_page_below_min_chars"
_MIN_TEXT_CHARS = 200


def _resolve_version() -> str:
    try:
        return version("trafilatura")
    except PackageNotFoundError:
        return "unknown"


PARSER_VERSION = _resolve_version()


class TrafilaturaParser:
    """Parser converting HTML to markdown via trafilatura.

    Conforms to :class:`corpus.parsers.base.Parser`.
    """

    name: str = PARSER_NAME
    version: str = PARSER_VERSION

    def parse(
        self,
        raw: bytes | str,
        url: str,
        content_type: str = "text/html",
    ) -> ParsedDocument:
        html = _coerce_html(raw)
        parsed_at = datetime.now(UTC)

        if not html:
            return ParsedDocument(
                url=url,
                parser=self.name,
                parser_version=self.version,
                parsed_at=parsed_at,
                content_type=content_type or "text/html",
                text="",
                text_format="markdown",
                error="empty_input",
                meta={},
            )

        try:
            text = trafilatura.extract(
                html,
                url=url,
                output_format="markdown",
                include_links=True,
                include_tables=True,
                with_metadata=False,
                favor_recall=True,
            )
        except Exception as exc:  # noqa: BLE001 — diagnostics flow through .error
            return ParsedDocument(
                url=url,
                parser=self.name,
                parser_version=self.version,
                parsed_at=parsed_at,
                content_type=content_type or "text/html",
                text="",
                text_format="markdown",
                error=f"trafilatura_extract_failed: {exc}",
                meta={},
            )

        if not text or len(text) < _MIN_TEXT_CHARS:
            return ParsedDocument(
                url=url,
                parser=self.name,
                parser_version=self.version,
                parsed_at=parsed_at,
                content_type=content_type or "text/html",
                text="",
                text_format="markdown",
                error=LANDING_PAGE_ERROR,
                meta={"extracted_chars": len(text) if text else 0},
            )

        return ParsedDocument(
            url=url,
            parser=self.name,
            parser_version=self.version,
            parsed_at=parsed_at,
            content_type=content_type or "text/html",
            text=text,
            text_format="markdown",
            error="",
            meta={},
        )


def _coerce_html(raw: bytes | str) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


# ---------------------------------------------------------------------------
# CLI — pulls raw HTML from `web_items.html_raw` (per OQ-2)
# ---------------------------------------------------------------------------


def _unwrap(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _cli(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(
        description=(
            "Parse web_items rows via trafilatura and write to the "
            "Mongo `parsed_documents` collection."
        )
    )
    cli.add_argument("--limit", type=int, default=None, help="Process at most N rows")
    cli.add_argument(
        "--url", type=str, default=None, help="Restrict to a single URL"
    )
    cli.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the parser but don't write to Mongo (counts only)",
    )
    args = cli.parse_args(argv)

    parser = TrafilaturaParser()
    client: MongoClient = MongoClient(MONGO_URI)
    try:
        bootstrap_indexes(client=client)
        col = client[MONGO_DB]["web_items"]
        query: dict[str, object] = {"content_type": "text/html"}
        if args.url:
            query["url"] = args.url

        cursor = col.find(query)
        if args.limit:
            cursor = cursor.limit(args.limit)

        written = errors = skipped = landing = 0
        for row in cursor:
            url = _unwrap(row.get("url") or row.get("_id"))
            html = _unwrap(row.get("html_raw"))
            if not isinstance(url, str) or not isinstance(html, str):
                skipped += 1
                continue
            doc = parser.parse(html, url=url, content_type="text/html")
            if doc.error == LANDING_PAGE_ERROR:
                landing += 1
            elif doc.error:
                errors += 1
            if args.dry_run:
                continue
            try:
                write_parsed_document(doc, client=client)
                written += 1
            except Exception as exc:  # noqa: BLE001
                _log.error("write failed for %s: %s", url, exc)
                errors += 1

        print(
            f"\nDone — written={written} errors={errors}"
            f" skipped={skipped} landing_pages={landing}"
        )
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
