"""MongoDB adaptor: yields QARecord from web_items (HTML) and parsed_pdfs (PDF).

web_items schema:  {_id, url: [str], content_type: [str], html_raw: str}
parsed_pdfs schema: {_id: url_str, markdown: str, error: str, ...}
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection

from corpus.extractors.html_extractor import extract_from_html
from corpus.extractors.pdf_extractor import extract_from_markdown
from corpus.models import QARecord

log = logging.getLogger(__name__)

# Default queries — callers may override to scope extraction.
_DEFAULT_HTML_QUERY: dict[str, Any] = {"content_type": "text/html"}
_DEFAULT_PDF_QUERY: dict[str, Any] = {"error": ""}


def records_from_mongodb(
    host: str,
    db: str,
    html_query: dict[str, Any] | None = None,
    pdf_query: dict[str, Any] | None = None,
) -> Iterator[QARecord]:
    """Stream QARecords from MongoDB web_items (HTML) and parsed_pdfs (PDF).

    Args:
        host:       MongoDB URI, e.g. ``"mongodb://localhost:27017/"``
        db:         Database name, e.g. ``"ema_scraper"``
        html_query: Override filter for the web_items HTML query.
        pdf_query:  Override filter for the parsed_pdfs query.
    """
    if html_query is None:
        html_query = _DEFAULT_HTML_QUERY
    if pdf_query is None:
        pdf_query = _DEFAULT_PDF_QUERY

    client: MongoClient[Any] = MongoClient(host)
    try:
        yield from _html_records(client[db]["web_items"], html_query)
        yield from _pdf_records(client[db]["parsed_pdfs"], pdf_query)
    finally:
        client.close()


def _html_records(
    col: Collection[Any],
    query: dict[str, Any],
) -> Iterator[QARecord]:
    for doc in col.find(query):
        url_list: list[str] = doc.get("url", [])
        if not url_list:
            continue
        url = url_list[0]
        html_raw = doc.get("html_raw", "")
        # web_items stores html_raw as a 1-element list; normalise to str.
        if isinstance(html_raw, list):
            html_raw = html_raw[0] if html_raw else ""
        html: str = html_raw
        if not html:
            continue
        try:
            yield from extract_from_html(html, url)
        except Exception as exc:
            log.warning("HTML extract failed for %s: %s", url, exc)


def _pdf_records(
    col: Collection[Any],
    query: dict[str, Any],
) -> Iterator[QARecord]:
    for doc in col.find(query):
        url: str = doc["_id"]
        markdown: str = doc.get("markdown", "")
        if not markdown:
            continue
        try:
            yield from extract_from_markdown(markdown, url)
        except Exception as exc:
            log.warning("PDF extract failed for %s: %s", url, exc)
