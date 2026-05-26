"""Pure-Python tests for the MIGR-007 sync helpers.

These exercise the preference selector and hash-skip path without hitting
PG or Mongo — DB-touching cases live in tests/test_embed_pg_sync.py
(added in MIGR-010).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from corpus.parsers.base import ParsedDocument
from harness import embed_pg


def _row(
    *,
    url: str = "https://x.test/a.pdf",
    parser: str = "pymupdf4llm",
    parser_version: str = "1.27.2",
    content_type: str = "application/pdf",
    text: str = "# Title\n\nbody",
    text_format: str = "markdown",
    error: str = "",
    meta: dict | None = None,
    parsed_at: datetime | None = None,
) -> dict:
    return {
        "url": url,
        "parser": parser,
        "parser_version": parser_version,
        "parsed_at": parsed_at or datetime(2026, 5, 26, 12, 0, tzinfo=UTC),
        "content_type": content_type,
        "text": text,
        "text_format": text_format,
        "error": error,
        "meta": meta or {},
    }


# ---------------------------------------------------------------------------
# compute_parsed_text_hash
# ---------------------------------------------------------------------------


def test_parsed_text_hash_is_deterministic():
    h1 = embed_pg.compute_parsed_text_hash("# Title\n\nbody.")
    h2 = embed_pg.compute_parsed_text_hash("# Title\n\nbody.")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_parsed_text_hash_trims_trailing_whitespace():
    a = embed_pg.compute_parsed_text_hash("body")
    b = embed_pg.compute_parsed_text_hash("body   \n\n")
    assert a == b


def test_parsed_text_hash_differs_on_content_change():
    a = embed_pg.compute_parsed_text_hash("body 1")
    b = embed_pg.compute_parsed_text_hash("body 2")
    assert a != b


def test_parsed_text_hash_empty_input():
    h = embed_pg.compute_parsed_text_hash("")
    assert len(h) == 64


# ---------------------------------------------------------------------------
# _select_preferred — the preference selector
# ---------------------------------------------------------------------------


def test_select_returns_first_preferred_parser():
    rows = [
        _row(parser="pymupdf4llm"),
        _row(parser="llamahub_pdf"),
    ]
    pref = {"application/pdf": ["pymupdf4llm", "llamahub_pdf"]}
    selected = embed_pg._select_preferred(rows, pref)
    assert selected is not None
    assert selected["parser"] == "pymupdf4llm"


def test_select_falls_back_to_second_preferred():
    rows = [_row(parser="llamahub_pdf")]
    pref = {"application/pdf": ["pymupdf4llm", "llamahub_pdf"]}
    selected = embed_pg._select_preferred(rows, pref)
    assert selected is not None
    assert selected["parser"] == "llamahub_pdf"


def test_select_returns_none_when_no_parser_in_preference():
    rows = [_row(parser="some_other_parser")]
    pref = {"application/pdf": ["pymupdf4llm"]}
    assert embed_pg._select_preferred(rows, pref) is None


def test_select_skips_error_rows():
    rows = [
        _row(parser="pymupdf4llm", error="upstream_failed"),
        _row(parser="llamahub_pdf"),
    ]
    pref = {"application/pdf": ["pymupdf4llm", "llamahub_pdf"]}
    selected = embed_pg._select_preferred(rows, pref)
    assert selected is not None
    assert selected["parser"] == "llamahub_pdf"


def test_select_empty_rows_returns_none():
    assert embed_pg._select_preferred([], {"application/pdf": ["pymupdf4llm"]}) is None


def test_select_no_content_type_in_preference():
    rows = [_row(content_type="application/xml", parser="any")]
    pref = {"application/pdf": ["pymupdf4llm"]}
    assert embed_pg._select_preferred(rows, pref) is None


def test_select_html_content_type():
    rows = [_row(content_type="text/html", parser="trafilatura", url="https://x.test/")]
    pref = {"text/html": ["trafilatura"]}
    selected = embed_pg._select_preferred(rows, pref)
    assert selected is not None
    assert selected["parser"] == "trafilatura"


# ---------------------------------------------------------------------------
# _mongo_row_to_parsed_doc
# ---------------------------------------------------------------------------


def test_round_trip_through_mongo_shape():
    row = _row(text="content", parser_version="1.27.2")
    parsed = embed_pg._mongo_row_to_parsed_doc(row)
    assert isinstance(parsed, ParsedDocument)
    assert parsed.url == row["url"]
    assert parsed.parser == "pymupdf4llm"
    assert parsed.parser_version == "1.27.2"
    assert parsed.text == "content"


def test_round_trip_restores_utc_tzinfo_when_missing():
    naive = datetime(2026, 5, 26, 12, 0)  # tz-naive
    row = _row(parsed_at=naive)
    parsed = embed_pg._mongo_row_to_parsed_doc(row)
    assert parsed.parsed_at.tzinfo is not None


def test_round_trip_missing_parsed_at_raises():
    row = _row()
    del row["parsed_at"]
    with pytest.raises(ValueError, match="parsed_at"):
        embed_pg._mongo_row_to_parsed_doc(row)


# ---------------------------------------------------------------------------
# _document_input_from_parsed
# ---------------------------------------------------------------------------


def test_document_input_from_parsed_pdf():
    parsed = ParsedDocument(
        url="https://www.ema.europa.eu/en/documents/qa.pdf",
        parser="pymupdf4llm",
        parser_version="1.27.2",
        parsed_at=datetime(2026, 5, 26, tzinfo=UTC),
        content_type="application/pdf",
        text="# Title\n\nbody",
        text_format="markdown",
        meta={"cache_path": "/tmp/x"},
    )
    d = embed_pg._document_input_from_parsed(parsed)
    assert d.source_url == parsed.url
    assert d.source_type == "pdf"
    assert d.title == "Title"
    assert d.topic_path == "/en/documents/"
    assert d.markdown == "# Title\n\nbody"
    assert d.raw_byte_size == len(b"# Title\n\nbody")
    assert d.meta["parser"] == "pymupdf4llm"
    assert d.meta["parser_version"] == "1.27.2"
    assert d.meta["cache_path"] == "/tmp/x"


def test_document_input_from_parsed_html():
    parsed = ParsedDocument(
        url="https://www.ema.europa.eu/en/questions-answers",
        parser="trafilatura",
        parser_version="2.0.0",
        parsed_at=datetime(2026, 5, 26, tzinfo=UTC),
        content_type="text/html",
        text="# H\n\nbody text",
        text_format="markdown",
    )
    d = embed_pg._document_input_from_parsed(parsed)
    assert d.source_type == "html"
    assert d.topic_path == "/en/questions-answers/"
