"""Base types for the parsers layer.

`ParsedDocument` is the wire-format every parser produces and the Mongo
``parsed_documents`` collection stores. The triple
``(url, parser, parser_version)`` is the compound unique key, allowing
different parsers and parser versions to coexist for the same URL.

Field semantics:
    url            — source URL (the input to the parser)
    parser         — parser identifier, e.g. ``"pymupdf4llm"``, ``"trafilatura"``
    parser_version — pinned version of the parser, e.g. ``"1.27.2"``
    parsed_at      — UTC timestamp when the parser ran
    content_type   — MIME type of the input, e.g. ``"application/pdf"``,
                     ``"text/html"``
    text           — parsed output (may be empty when ``error`` is set)
    text_format    — one of ``"markdown"``, ``"html"``, ``"plain"``
    error          — empty string when parse succeeded; non-empty diagnostic
                     string when it failed (downstream skip)
    meta           — free-form per-parser metadata (e.g. ``cache_path``)

Construction raises ``ValueError`` for malformed input so bad rows never
reach Mongo. The Parser protocol itself is added in MIGR-004.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, get_args

TextFormat = Literal["markdown", "html", "plain"]

VALID_TEXT_FORMATS: tuple[str, ...] = get_args(TextFormat)


@dataclass
class ParsedDocument:
    url: str
    parser: str
    parser_version: str
    parsed_at: datetime
    content_type: str
    text: str
    text_format: TextFormat
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate(self)

    def to_mongo(self) -> dict[str, Any]:
        """Return a plain dict suitable for ``$set`` in a Mongo upsert."""
        return {
            "url": self.url,
            "parser": self.parser,
            "parser_version": self.parser_version,
            "parsed_at": self.parsed_at,
            "content_type": self.content_type,
            "text": self.text,
            "text_format": self.text_format,
            "error": self.error,
            "meta": dict(self.meta),
        }


def _validate(doc: ParsedDocument) -> None:
    if not isinstance(doc.url, str) or not doc.url:
        raise ValueError("ParsedDocument.url must be a non-empty string")
    if not isinstance(doc.parser, str) or not doc.parser:
        raise ValueError("ParsedDocument.parser must be a non-empty string")
    if not isinstance(doc.parser_version, str) or not doc.parser_version:
        raise ValueError("ParsedDocument.parser_version must be a non-empty string")
    if not isinstance(doc.parsed_at, datetime):
        raise ValueError("ParsedDocument.parsed_at must be a datetime")
    if not isinstance(doc.content_type, str) or not doc.content_type:
        raise ValueError("ParsedDocument.content_type must be a non-empty string")
    if not isinstance(doc.text, str):
        raise ValueError("ParsedDocument.text must be a string")
    if doc.text_format not in VALID_TEXT_FORMATS:
        raise ValueError(
            f"ParsedDocument.text_format must be one of {VALID_TEXT_FORMATS}, "
            f"got {doc.text_format!r}"
        )
    if not isinstance(doc.error, str):
        raise ValueError("ParsedDocument.error must be a string")
    if not isinstance(doc.meta, dict):
        raise ValueError("ParsedDocument.meta must be a dict")
