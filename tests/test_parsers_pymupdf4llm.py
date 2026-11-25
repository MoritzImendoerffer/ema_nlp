"""Unit tests for corpus/parsers/pymupdf4llm.py.

The real Scrapy cache ships pickled ``PdfDocument`` instances whose class
lives in the ``ema_scraper`` repo (not a project dep here). For unit tests we
pickle a ``types.SimpleNamespace`` instead — it satisfies the duck-typing
the parser does (``.markdown``, ``.error``, ``.parsed_with``).
"""

from __future__ import annotations

import pickle
from datetime import datetime
from types import SimpleNamespace

from corpus.parsers.base import ParsedDocument, Parser
from corpus.parsers.pymupdf4llm import (
    PARSER_NAME,
    PARSER_VERSION,
)
from corpus.parsers.pymupdf4llm import LegacyPickleReader as PymuPdf4LlmParser


def _pickle_doc(markdown: str = "# T\n\nbody", error: str = "", parsed_with: str = "pymupdf4llm") -> bytes:
    return pickle.dumps(SimpleNamespace(markdown=markdown, error=error, parsed_with=parsed_with))


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_class_satisfies_parser_protocol() -> None:
    parser = PymuPdf4LlmParser()
    assert isinstance(parser, Parser)


def test_name_and_version_are_set() -> None:
    parser = PymuPdf4LlmParser()
    assert parser.name == PARSER_NAME == "pymupdf4llm"
    assert parser.version == PARSER_VERSION
    assert isinstance(parser.version, str) and parser.version


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_parse_pickle_bytes_returns_parsed_document() -> None:
    parser = PymuPdf4LlmParser()
    url = "https://www.ema.europa.eu/en/documents/x.pdf"
    doc = parser.parse(_pickle_doc("# Title\n\nbody."), url=url, content_type="application/pdf")

    assert isinstance(doc, ParsedDocument)
    assert doc.url == url
    assert doc.parser == "pymupdf4llm"
    assert doc.parser_version == PARSER_VERSION
    assert doc.content_type == "application/pdf"
    assert doc.text == "# Title\n\nbody."
    assert doc.text_format == "markdown"
    assert doc.error == ""
    assert doc.meta.get("parsed_with") == "pymupdf4llm"
    assert isinstance(doc.parsed_at, datetime)


def test_parse_uses_default_content_type_when_empty() -> None:
    parser = PymuPdf4LlmParser()
    doc = parser.parse(_pickle_doc("x" * 50), url="https://x.test/x.pdf", content_type="")
    assert doc.content_type == "application/pdf"


def test_parse_path_str_reads_pickle_file(tmp_path) -> None:
    pkl = tmp_path / "parsed_pdf.pkl"
    pkl.write_bytes(_pickle_doc("# File mode\n\nfrom disk."))
    parser = PymuPdf4LlmParser()
    doc = parser.parse(str(pkl), url="https://x.test/a.pdf", content_type="application/pdf")
    assert doc.text == "# File mode\n\nfrom disk."
    assert doc.meta.get("cache_path") == str(pkl)


# ---------------------------------------------------------------------------
# Error rows
# ---------------------------------------------------------------------------


def test_parse_propagates_parser_internal_error() -> None:
    parser = PymuPdf4LlmParser()
    doc = parser.parse(
        _pickle_doc(markdown="", error="upstream pdf parse failed"),
        url="https://x.test/broken.pdf",
        content_type="application/pdf",
    )
    assert doc.error == "upstream pdf parse failed"
    assert doc.text == ""


def test_parse_handles_empty_bytes() -> None:
    parser = PymuPdf4LlmParser()
    doc = parser.parse(b"", url="https://x.test/x.pdf", content_type="application/pdf")
    assert doc.error == "empty_input"
    assert doc.text == ""


def test_parse_handles_corrupt_pickle() -> None:
    parser = PymuPdf4LlmParser()
    doc = parser.parse(b"not a pickle", url="https://x.test/x.pdf", content_type="application/pdf")
    assert doc.error.startswith("pickle_load_failed")
    assert doc.text == ""


def test_parse_handles_missing_path(tmp_path) -> None:
    parser = PymuPdf4LlmParser()
    missing = tmp_path / "nope.pkl"
    doc = parser.parse(str(missing), url="https://x.test/x.pdf", content_type="application/pdf")
    assert doc.error.startswith("pickle_load_failed")


def test_parse_handles_missing_attrs_on_unpickled_obj() -> None:
    """Pickle a bare object — missing markdown attr → empty text, no crash."""
    parser = PymuPdf4LlmParser()
    bare = pickle.dumps(SimpleNamespace())  # no .markdown, .error, .parsed_with
    doc = parser.parse(bare, url="https://x.test/x.pdf", content_type="application/pdf")
    assert doc.text == ""
    assert doc.error == ""
    # parsed_with also absent → meta should not carry the key
    assert "parsed_with" not in doc.meta


# ---------------------------------------------------------------------------
# Round-trip: parsed shape ready for the Mongo writer
# ---------------------------------------------------------------------------


def test_parsed_document_to_mongo_round_trip() -> None:
    parser = PymuPdf4LlmParser()
    doc = parser.parse(_pickle_doc("x" * 100), url="https://x.test/x.pdf", content_type="application/pdf")
    mongo_doc = doc.to_mongo()
    assert mongo_doc["url"] == "https://x.test/x.pdf"
    assert mongo_doc["parser"] == "pymupdf4llm"
    assert mongo_doc["parser_version"] == PARSER_VERSION
    assert mongo_doc["text_format"] == "markdown"
    assert mongo_doc["content_type"] == "application/pdf"


# ---------------------------------------------------------------------------
# Bad input — never raises
# ---------------------------------------------------------------------------


def test_parse_does_not_raise_on_garbage_inputs() -> None:
    parser = PymuPdf4LlmParser()
    for bad in (b"", b"   ", b"\x00\x01\x02"):
        d = parser.parse(bad, url="https://x.test/x.pdf", content_type="application/pdf")
        assert isinstance(d, ParsedDocument)


def test_parse_with_none_input_returns_error_doc() -> None:
    parser = PymuPdf4LlmParser()
    # None is not bytes|str — _load_pickle treats it as empty; ParsedDocument
    # is still well-formed with error='empty_input'.
    d = parser.parse(None, url="https://x.test/x.pdf", content_type="application/pdf")  # type: ignore[arg-type]
    assert d.error == "empty_input"


# ---------------------------------------------------------------------------
# The byte parser (TASK-009 of work unit 27)
#
# Until 2026-11-25 the module parsed no PDF: it unpickled the scraper's holders,
# which failed outside the scraper's path with "No module named 'parsers'".
# ---------------------------------------------------------------------------

import gzip  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from corpus.parsers.pymupdf4llm import PymuPdf4LlmParser as BytesParser  # noqa: E402

_FIXTURE = Path(__file__).parent / "fixtures" / "fixture_pdf_0.pdf"
_URL = "https://www.ema.europa.eu/en/documents/scientific-guideline/fixture_en.pdf"


@pytest.fixture(scope="module")
def parsed_plain():
    return BytesParser().parse(_FIXTURE.read_bytes(), url=_URL)


@pytest.fixture(scope="module")
def parsed_gzip():
    return BytesParser().parse(gzip.compress(_FIXTURE.read_bytes()), url=_URL)


def test_pdf_parser_reads_bytes(parsed_plain):
    assert parsed_plain.error == ""
    assert len(parsed_plain.text) > 1000  # 11,906 characters on 2026-11-23 (OCR on)
    assert parsed_plain.parser == "pymupdf4llm"
    assert parsed_plain.parser_version == PARSER_VERSION
    assert "parsers" not in sys.modules  # the scraper's package is never imported


def test_gzip_body_is_decompressed(parsed_plain, parsed_gzip):
    # Two separate parses of the same PDF: equal text also shows the output is stable.
    assert parsed_gzip.error == ""
    assert parsed_gzip.text == parsed_plain.text
    assert parsed_gzip.meta["gzip"] is True and parsed_plain.meta["gzip"] is False


def test_meta_records_options(parsed_plain):
    meta = parsed_plain.meta
    assert meta["use_ocr"] is True and meta["header"] is True and meta["footer"] is True
    assert meta["layout"] is True
    assert set(meta["versions"]) == {"pymupdf4llm", "pymupdf", "pymupdf-layout"}
    assert meta["versions"]["pymupdf4llm"] == PARSER_VERSION


def test_not_a_pdf_returns_error():
    doc = BytesParser().parse(b"hello", url=_URL)
    assert doc.text == ""
    assert doc.error.startswith("pdf_open_failed")


def test_empty_and_bad_gzip_bodies_return_errors():
    assert BytesParser().parse(b"", url=_URL).error == "empty_input"
    assert BytesParser().parse(b"\x1f\x8b not gzip", url=_URL).error.startswith("gzip_failed")
