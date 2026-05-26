"""Unit tests for corpus/parsers/trafilatura.py.

The fixture HTML is the same one ``tests/test_html_normaliser.py`` uses, so
parity with the legacy ``normalise_html`` output is locked in.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from corpus.ingestion.html_normaliser import normalise_html
from corpus.parsers.base import ParsedDocument, Parser
from corpus.parsers.trafilatura import (
    LANDING_PAGE_ERROR,
    PARSER_NAME,
    PARSER_VERSION,
    TrafilaturaParser,
)

FIXTURES = Path(__file__).parent / "fixtures"
HTML_SAMPLE = (FIXTURES / "ema_html_sample.html").read_text(encoding="utf-8")
HTML_LANDING = (FIXTURES / "ema_nav_landing.html").read_text(encoding="utf-8")
SAMPLE_URL = "https://www.ema.europa.eu/en/sampling-questions-answers"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_class_satisfies_parser_protocol() -> None:
    parser = TrafilaturaParser()
    assert isinstance(parser, Parser)


def test_name_and_version_are_set() -> None:
    parser = TrafilaturaParser()
    assert parser.name == PARSER_NAME == "trafilatura"
    assert parser.version == PARSER_VERSION
    assert isinstance(parser.version, str) and parser.version


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_parse_html_sample_returns_parsed_document() -> None:
    parser = TrafilaturaParser()
    doc = parser.parse(HTML_SAMPLE, url=SAMPLE_URL, content_type="text/html")

    assert isinstance(doc, ParsedDocument)
    assert doc.url == SAMPLE_URL
    assert doc.parser == "trafilatura"
    assert doc.parser_version == PARSER_VERSION
    assert doc.content_type == "text/html"
    assert doc.text_format == "markdown"
    assert doc.error == ""
    assert len(doc.text) >= 200
    assert isinstance(doc.parsed_at, datetime)


def test_parse_matches_legacy_normalise_html_output() -> None:
    """Parity: the new parser's text must equal what normalise_html produced."""
    parser = TrafilaturaParser()
    doc = parser.parse(HTML_SAMPLE, url=SAMPLE_URL, content_type="text/html")
    legacy = normalise_html(HTML_SAMPLE, SAMPLE_URL)
    assert legacy is not None
    assert doc.text == legacy.markdown


def test_parse_accepts_bytes_input() -> None:
    parser = TrafilaturaParser()
    doc = parser.parse(HTML_SAMPLE.encode("utf-8"), url=SAMPLE_URL, content_type="text/html")
    assert doc.error == ""
    assert doc.text


def test_parse_defaults_to_text_html_when_content_type_empty() -> None:
    parser = TrafilaturaParser()
    doc = parser.parse(HTML_SAMPLE, url=SAMPLE_URL, content_type="")
    assert doc.content_type == "text/html"


# ---------------------------------------------------------------------------
# Landing-page guard
# ---------------------------------------------------------------------------


def test_landing_page_short_extracted_text_produces_error_row() -> None:
    parser = TrafilaturaParser()
    doc = parser.parse(HTML_LANDING, url="https://x.test/landing", content_type="text/html")
    assert doc.error == LANDING_PAGE_ERROR
    assert doc.text == ""
    assert "extracted_chars" in doc.meta


def test_landing_page_legacy_returns_none_new_returns_error_row() -> None:
    """Cross-check: legacy returned None; new parser emits an error row."""
    legacy = normalise_html(HTML_LANDING, "https://x.test/landing")
    assert legacy is None
    parser = TrafilaturaParser()
    doc = parser.parse(HTML_LANDING, url="https://x.test/landing", content_type="text/html")
    assert doc.error == LANDING_PAGE_ERROR


# ---------------------------------------------------------------------------
# Bad input — never raises
# ---------------------------------------------------------------------------


def test_parse_empty_string_returns_empty_input_error() -> None:
    parser = TrafilaturaParser()
    doc = parser.parse("", url=SAMPLE_URL, content_type="text/html")
    assert doc.error == "empty_input"


def test_parse_empty_bytes_returns_empty_input_error() -> None:
    parser = TrafilaturaParser()
    doc = parser.parse(b"", url=SAMPLE_URL, content_type="text/html")
    assert doc.error == "empty_input"


def test_parse_garbage_html_does_not_raise() -> None:
    parser = TrafilaturaParser()
    for garbage in ("not html", "<<>>random<<", "<html><body></body></html>"):
        doc = parser.parse(garbage, url=SAMPLE_URL, content_type="text/html")
        assert isinstance(doc, ParsedDocument)
        # Either landing-page error (too short) or empty_input is acceptable
        assert doc.error in {LANDING_PAGE_ERROR, "empty_input"}


def test_parse_handles_bytes_with_bad_encoding() -> None:
    parser = TrafilaturaParser()
    # Mixed encoding: latin-1 byte inside what is otherwise utf-8
    html = "<html><body><p>caf\xe9</p>" + ("padding text " * 100) + "</body></html>"
    raw = html.encode("latin-1")
    doc = parser.parse(raw, url=SAMPLE_URL, content_type="text/html")
    assert isinstance(doc, ParsedDocument)
    # We don't crash; what trafilatura extracts is its business.


# ---------------------------------------------------------------------------
# Round-trip ready for the Mongo writer
# ---------------------------------------------------------------------------


def test_parsed_document_to_mongo_round_trip() -> None:
    parser = TrafilaturaParser()
    doc = parser.parse(HTML_SAMPLE, url=SAMPLE_URL, content_type="text/html")
    mongo_doc = doc.to_mongo()
    assert mongo_doc["url"] == SAMPLE_URL
    assert mongo_doc["parser"] == "trafilatura"
    assert mongo_doc["parser_version"] == PARSER_VERSION
    assert mongo_doc["text_format"] == "markdown"
    assert mongo_doc["content_type"] == "text/html"
