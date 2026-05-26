"""Text-derived metadata extractors.

Five regex-based fields lifted out of ``corpus/ingestion/pdf_normaliser.py``
so the sync layer can call ``text_metadata(text, text_format)`` without
knowing whether the text came from a PDF or an HTML page.

Fields:
    title             — first markdown H1
    reference_number  — first ``EMA/.../YYYY`` match in the document header
    committee         — CHMP/PRAC/CVMP/COMP/PDCO/CAT segment of the reference
    revision          — ``Rev. N`` / ``Revision N`` near the top
    last_updated      — ``DD Month YYYY`` header date

All fields degrade to ``None`` when not found; a debug-level
``"metadata missing: <field>"`` log line is emitted in that case.

The regexes are also exported for reuse by ``corpus/ingestion/link_extractor.py``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

EMA_REF_RE = re.compile(r"\bEMA/[A-Z0-9][A-Z0-9/\-]*?/\d{2,7}/\d{4}\b")
_COMMITTEES = ("CHMP", "PRAC", "CVMP", "COMP", "PDCO", "CAT")
_COMMITTEE_RE = re.compile(r"\bEMA/([A-Z]+)/")
_REVISION_RE = re.compile(r"\b(?:Rev(?:ision)?\.?\s*)(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{4})\b"
)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

_log = logging.getLogger(__name__)

TextFormat = Literal["markdown", "html", "plain"]


@dataclass(frozen=True)
class TextMetadata:
    title: str | None
    reference_number: str | None
    committee: str | None
    revision: str | None
    last_updated: datetime | None


def _extract_title(text: str) -> str | None:
    m = _H1_RE.search(text)
    if not m:
        return None
    title = m.group(1).strip().strip("*").strip()
    return title or None


def _extract_committee(reference_number: str | None) -> str | None:
    if not reference_number:
        return None
    m = _COMMITTEE_RE.match(reference_number)
    if not m:
        return None
    candidate = m.group(1)
    return candidate if candidate in _COMMITTEES else None


def _extract_last_updated(text: str) -> datetime | None:
    header = text[:1024]
    m = _DATE_RE.search(header)
    if not m:
        return None
    day, month, year = m.group(1), m.group(2).lower(), m.group(3)
    try:
        return datetime(int(year), _MONTHS[month], int(day), tzinfo=UTC)
    except (KeyError, ValueError):
        return None


def text_metadata(text: str, text_format: TextFormat = "markdown") -> TextMetadata:
    """Extract the five metadata fields from a parsed text body.

    ``text_format`` is currently informational — the regexes target
    markdown headers, so HTML or plain text inputs will mostly produce
    ``None`` fields. Future parsers that emit non-markdown could grow
    text_format-specific branches here.
    """
    header = text[:2048] if isinstance(text, str) else ""

    title = _extract_title(text) if text else None
    if title is None:
        _log.debug("metadata missing: title")

    ref_match = EMA_REF_RE.search(header) if header else None
    reference_number = ref_match.group(0) if ref_match else None
    if reference_number is None:
        _log.debug("metadata missing: reference_number")

    committee = _extract_committee(reference_number)
    if committee is None:
        _log.debug("metadata missing: committee")

    revision_match = _REVISION_RE.search(header) if header else None
    revision = revision_match.group(1) if revision_match else None
    if revision is None:
        _log.debug("metadata missing: revision")

    last_updated = _extract_last_updated(text) if text else None
    if last_updated is None:
        _log.debug("metadata missing: last_updated")

    return TextMetadata(
        title=title,
        reference_number=reference_number,
        committee=committee,
        revision=revision,
        last_updated=last_updated,
    )
