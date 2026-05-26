"""Normalise a parsed_pdfs MongoDB doc into a DocumentInput row.

Public API:
    DocumentInput      — shape passed into the ingest upsert layer
    normalise_pdf_doc  — accept one mongo doc, emit DocumentInput | None
    EMA_REF_RE         — reference-number regex (also used by link_extractor)

`parsed_pdfs` documents have keys: _id (URL), cache_path, error, ingested_at,
markdown, parsed_with. Markdown is pymupdf4llm output. We extract:

    title             — first markdown H1, else URL basename
    reference_number  — first 'EMA/.../YYYY' match in the markdown header
    committee         — CHMP/PRAC/CVMP/COMP/PDCO/CAT segment of the
                        reference, when present
    revision          — 'Rev. N' / 'Revision N' if found near the top
    last_updated      — 'DD Month YYYY' header date if found; else None
    topic_path        — URL path segment up to but not including filename
    raw_byte_size     — len(markdown.encode('utf-8'))

Returns None when markdown is empty/whitespace or `error` is non-empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

# Regexes and constants live in corpus/metadata/text_metadata.py (MIGR-003).
# Re-export them here so existing callers (link_extractor, html_normaliser,
# test_pdf_normaliser) continue to work unchanged until the Phase C cleanup.
from corpus.metadata.text_metadata import (
    _COMMITTEE_RE,
    _COMMITTEES,
    _DATE_RE,
    _H1_RE,
    _MONTHS,
    _REVISION_RE,
    EMA_REF_RE,
)

__all__ = [
    "DocumentInput",
    "EMA_REF_RE",
    "normalise_pdf_doc",
    "_COMMITTEES",
    "_COMMITTEE_RE",
    "_DATE_RE",
    "_H1_RE",
    "_MONTHS",
    "_REVISION_RE",
]


@dataclass
class DocumentInput:
    source_url: str
    source_type: Literal["pdf", "html"]
    title: str | None
    topic_path: str | None
    reference_number: str | None
    committee: str | None
    revision: str | None
    last_updated: datetime | None
    raw_byte_size: int | None
    markdown: str
    meta: dict[str, Any] = field(default_factory=dict)


def _extract_title(markdown: str, source_url: str) -> str | None:
    m = _H1_RE.search(markdown)
    if m:
        title = m.group(1).strip().strip("*").strip()
        if title:
            return title
    path = urlparse(source_url).path
    if path:
        basename = path.rsplit("/", 1)[-1]
        if basename:
            stem = basename.rsplit(".", 1)[0]
            return stem.replace("_", " ").replace("-", " ").strip() or None
    return None


def _extract_committee(reference_number: str | None) -> str | None:
    if not reference_number:
        return None
    m = _COMMITTEE_RE.match(reference_number)
    if not m:
        return None
    candidate = m.group(1)
    return candidate if candidate in _COMMITTEES else None


def _extract_last_updated(markdown: str) -> datetime | None:
    header = markdown[:1024]
    m = _DATE_RE.search(header)
    if not m:
        return None
    day, month, year = m.group(1), m.group(2).lower(), m.group(3)
    try:
        return datetime(int(year), _MONTHS[month], int(day), tzinfo=UTC)
    except (KeyError, ValueError):
        return None


def _extract_topic_path(source_url: str) -> str | None:
    path = urlparse(source_url).path
    if not path:
        return None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "/"
    # Drop filename (last segment when it has an extension)
    if "." in parts[-1]:
        parts = parts[:-1]
    return "/" + "/".join(parts) + "/" if parts else "/"


def normalise_pdf_doc(mongo_doc: dict[str, Any]) -> DocumentInput | None:
    """Return a DocumentInput, or None if the doc is unusable."""
    if not mongo_doc:
        return None
    if mongo_doc.get("error"):
        return None
    markdown = (mongo_doc.get("markdown") or "").strip()
    if not markdown:
        return None
    source_url = mongo_doc.get("_id") or mongo_doc.get("source_url")
    if not source_url:
        return None

    header = markdown[:2048]
    ref_match = EMA_REF_RE.search(header)
    reference_number = ref_match.group(0) if ref_match else None
    revision_match = _REVISION_RE.search(header)
    revision = revision_match.group(1) if revision_match else None

    return DocumentInput(
        source_url=source_url,
        source_type="pdf",
        title=_extract_title(markdown, source_url),
        topic_path=_extract_topic_path(source_url),
        reference_number=reference_number,
        committee=_extract_committee(reference_number),
        revision=revision,
        last_updated=_extract_last_updated(markdown),
        raw_byte_size=len(markdown.encode("utf-8")),
        markdown=markdown,
        meta={"parsed_with": mongo_doc.get("parsed_with")} if mongo_doc.get("parsed_with") else {},
    )
