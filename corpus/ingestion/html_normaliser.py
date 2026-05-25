"""Normalise an HTML page (raw HTML or a web_items Mongo doc) into a
DocumentInput row.

Public API:
    normalise_html(html, url) -> DocumentInput | None
    normalise_html_doc(mongo_doc) -> DocumentInput | None

Trafilatura does the extraction:
    output_format='markdown' produces well-structured markdown that flows
    into the same chunker the PDF path uses.
    include_links=True keeps the [text](url) inline so link_extractor can
    pull them out later (NARR-012).
    with_metadata=True populates title + date when available.

Landing-page guard: pages whose extracted text is under 200 chars are
treated as navigation/landing pages and return None.

`web_items` documents store each field as a 1-element list (url, html_raw,
content_type). `normalise_html_doc` unwraps those defensively.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import trafilatura

from corpus.ingestion.pdf_normaliser import (
    EMA_REF_RE,
    DocumentInput,
    _COMMITTEE_RE,
    _COMMITTEES,
    _REVISION_RE,
)

_log = logging.getLogger(__name__)

_MIN_TEXT_CHARS = 200


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    candidates = (value, value[:10])
    for cand in candidates:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                dt = datetime.strptime(cand, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
    return None


def _topic_path(url: str) -> str | None:
    path = urlparse(url).path
    if not path:
        return None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "/"
    if "." in parts[-1]:
        parts = parts[:-1]
    return "/" + "/".join(parts) + "/" if parts else "/"


def _title_from_url(url: str) -> str | None:
    path = urlparse(url).path
    if not path:
        return None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    return parts[-1].replace("-", " ").replace("_", " ").strip() or None


def _committee_for(reference: str | None) -> str | None:
    if not reference:
        return None
    m = _COMMITTEE_RE.match(reference)
    if not m:
        return None
    return m.group(1) if m.group(1) in _COMMITTEES else None


def normalise_html(html: str, url: str) -> DocumentInput | None:
    """Extract markdown + metadata from HTML. None for landing pages."""
    if not html or not url:
        return None
    try:
        markdown = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            with_metadata=False,
            favor_recall=True,
        )
    except Exception as e:  # noqa: BLE001
        _log.warning("trafilatura.extract failed for %r: %s", url, e)
        return None
    if not markdown or len(markdown) < _MIN_TEXT_CHARS:
        return None

    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
    except Exception:
        meta = None

    title = (getattr(meta, "title", None) or _title_from_url(url)) if meta else _title_from_url(url)
    date_str = getattr(meta, "date", None) if meta else None
    last_updated = _parse_iso_date(date_str)

    ref_match = EMA_REF_RE.search(markdown[:4096])
    reference_number = ref_match.group(0) if ref_match else None
    revision_match = _REVISION_RE.search(markdown[:4096])
    revision = revision_match.group(1) if revision_match else None

    return DocumentInput(
        source_url=url,
        source_type="html",
        title=title,
        topic_path=_topic_path(url),
        reference_number=reference_number,
        committee=_committee_for(reference_number),
        revision=revision,
        last_updated=last_updated,
        raw_byte_size=len(markdown.encode("utf-8")),
        markdown=markdown,
        meta={"extractor": "trafilatura"},
    )


def _unwrap(value: Any) -> Any:
    """web_items stores each field as a 1-element list; unwrap it defensively."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def normalise_html_doc(mongo_doc: dict[str, Any]) -> DocumentInput | None:
    """Adapter over a web_items mongo doc → normalise_html."""
    if not mongo_doc:
        return None
    url = _unwrap(mongo_doc.get("url") or mongo_doc.get("_id"))
    html = _unwrap(mongo_doc.get("html_raw"))
    if not isinstance(html, str) or not isinstance(url, str):
        return None
    return normalise_html(html, url)
