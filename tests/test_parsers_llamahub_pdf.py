"""Tests for corpus/parsers/llamahub_pdf.py (MIGR-014).

The llamahub PDF reader is behind the ``[parsers-llamahub]`` optional
extra. Tests that need the actual reader skip cleanly when the extra is
not installed; the protocol-conformance and import-error-path tests run
unconditionally.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from corpus.parsers.base import ParsedDocument, Parser
from corpus.parsers.llamahub_pdf import (
    PARSER_NAME,
    PARSER_VERSION,
    LlamaHubPDFParser,
)

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "fixture_pdf_0.pdf"

try:
    _HAS_LLAMAHUB = importlib.util.find_spec("llama_index.readers.file") is not None
except ModuleNotFoundError:
    # find_spec raises when a parent package is missing
    _HAS_LLAMAHUB = False


# ---------------------------------------------------------------------------
# Protocol + name/version (no extra required)
# ---------------------------------------------------------------------------


def test_class_satisfies_parser_protocol():
    parser = LlamaHubPDFParser()
    assert isinstance(parser, Parser)


def test_parser_name_includes_reader_class():
    parser = LlamaHubPDFParser()
    assert parser.name == PARSER_NAME == "llamahub_pdf_PDFReader"


def test_parser_version_is_string():
    parser = LlamaHubPDFParser()
    assert isinstance(parser.version, str) and parser.version


def test_parse_empty_input_returns_error_doc():
    """Empty bytes never touch the reader — works without the extra."""
    parser = LlamaHubPDFParser()
    doc = parser.parse(b"", url="https://x.test/x.pdf", content_type="application/pdf")
    assert isinstance(doc, ParsedDocument)
    assert doc.error == "empty_input"
    assert doc.text == ""


# ---------------------------------------------------------------------------
# Extra-required path — skip-clean when not installed
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _HAS_LLAMAHUB,
    reason="parsers-llamahub extra not installed (install via [parsers-llamahub])",
)
@pytest.mark.skipif(not FIXTURE_PDF.exists(), reason="PDF fixture not present")
def test_parse_fixture_pdf_returns_parsed_document():
    parser = LlamaHubPDFParser()
    raw = FIXTURE_PDF.read_bytes()
    doc = parser.parse(raw, url="https://x.test/fixture.pdf", content_type="application/pdf")
    assert isinstance(doc, ParsedDocument)
    assert doc.url == "https://x.test/fixture.pdf"
    assert doc.parser == PARSER_NAME
    assert doc.text_format == "markdown"
    # The fixture is small; just check we got some text and no error
    assert doc.text  # non-empty
    assert doc.error == ""


@pytest.mark.skipif(
    not _HAS_LLAMAHUB,
    reason="parsers-llamahub extra not installed",
)
@pytest.mark.skipif(not FIXTURE_PDF.exists(), reason="PDF fixture not present")
def test_parse_path_str(tmp_path):
    parser = LlamaHubPDFParser()
    copy = tmp_path / "fixture.pdf"
    copy.write_bytes(FIXTURE_PDF.read_bytes())
    doc = parser.parse(str(copy), url="https://x.test/fixture.pdf", content_type="application/pdf")
    assert doc.text


# ---------------------------------------------------------------------------
# Missing-extra path — runs without the extra installed
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    _HAS_LLAMAHUB,
    reason="extra is installed; can't exercise the import-error path",
)
def test_parse_returns_missing_extra_error_when_reader_absent():
    parser = LlamaHubPDFParser()
    # Need real bytes so we don't short-circuit on empty_input
    fake_pdf = b"%PDF-1.4\nfake\n%%EOF\n"
    doc = parser.parse(fake_pdf, url="https://x.test/x.pdf", content_type="application/pdf")
    assert doc.error.startswith("missing_extra")
