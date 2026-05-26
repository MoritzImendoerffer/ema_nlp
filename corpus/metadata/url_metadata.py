"""URL-derived metadata.

Two fields:

    source_type   — ``"pdf"`` for ``.pdf`` URLs (ignoring query strings),
                    ``"html"`` for plain web URLs (no extension or
                    ``.html``/``.htm``), ``"unknown"`` for anything else.
                    The authoritative source is ``ParsedDocument.content_type``;
                    this is a hint derived purely from the URL shape.
    topic_path    — URL path minus the filename when the last segment looks
                    like a file (has an extension). Always trailing-slash
                    terminated; root URLs return ``"/"``.

This module exists so the parser-agnostic sync layer doesn't have to know
about either pymupdf4llm's or trafilatura's metadata layouts. The two old
normalisers (``corpus/ingestion/{pdf,html}_normaliser.py``) had identical
``_topic_path``/``_extract_topic_path`` implementations; this is the
consolidated home.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

SourceType = Literal["pdf", "html", "unknown"]

_HTML_EXTS = {".html", ".htm"}


@dataclass(frozen=True)
class UrlMetadata:
    source_type: SourceType
    topic_path: str | None


def _topic_path(url: str) -> str | None:
    """Return the URL path with the filename segment dropped.

    Matches the behaviour of the legacy ``_topic_path``/
    ``_extract_topic_path`` helpers in ``corpus/ingestion/*_normaliser.py``.
    """
    path = urlparse(url).path
    if not path:
        return None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "/"
    # Drop filename (last segment when it has an extension)
    if "." in parts[-1]:
        parts = parts[:-1]
    return "/" + "/".join(parts) + "/" if parts else "/"


def _source_type(url: str) -> SourceType:
    """Best-effort URL-shape guess; ``content_type`` is the authoritative value."""
    path = urlparse(url).path
    if not path:
        return "unknown"
    last = path.rsplit("/", 1)[-1]
    if not last or "." not in last:
        # No filename or no extension → directory-style HTML URL.
        return "html"
    ext = "." + last.rsplit(".", 1)[-1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in _HTML_EXTS:
        return "html"
    return "unknown"


def url_metadata(url: str) -> UrlMetadata:
    """Return URL-derived metadata."""
    return UrlMetadata(
        source_type=_source_type(url),
        topic_path=_topic_path(url),
    )
