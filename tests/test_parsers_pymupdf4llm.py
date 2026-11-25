"""Unit tests for corpus/parsers/pymupdf4llm.py: the byte parser and its CLI.

The pickle reader and its 11 tests were removed on 2026-11-25 (decision G of work unit
27, docs/pm/decisions/2026-11-25_pickle-reader.md). Git keeps both.
"""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

import pytest

from corpus.parsers.base import ParsedDocument, Parser
from corpus.parsers.pymupdf4llm import (
    PARSER_NAME,
    PARSER_VERSION,
    PymuPdf4LlmParser,
)

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
# Bad input — never raises
# ---------------------------------------------------------------------------


def test_parse_does_not_raise_on_garbage_inputs() -> None:
    parser = PymuPdf4LlmParser()
    for bad in (b"", b"   ", b"\x00\x01\x02", None):
        d = parser.parse(bad, url="https://x.test/x.pdf", content_type="application/pdf")  # type: ignore[arg-type]
        assert isinstance(d, ParsedDocument)
        assert d.error and d.text == ""


# ---------------------------------------------------------------------------
# The byte parser (TASK-009 of work unit 27)
#
# Until 2026-11-25 the module parsed no PDF: it unpickled the scraper's holders,
# which failed outside the scraper's path with "No module named 'parsers'".
# ---------------------------------------------------------------------------



_FIXTURE = Path(__file__).parent / "fixtures" / "fixture_pdf_0.pdf"
_URL = "https://www.ema.europa.eu/en/documents/scientific-guideline/fixture_en.pdf"


@pytest.fixture(scope="module")
def parsed_plain():
    return PymuPdf4LlmParser().parse(_FIXTURE.read_bytes(), url=_URL)


@pytest.fixture(scope="module")
def parsed_gzip():
    return PymuPdf4LlmParser().parse(gzip.compress(_FIXTURE.read_bytes()), url=_URL)


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
    doc = PymuPdf4LlmParser().parse(b"hello", url=_URL)
    assert doc.text == ""
    assert doc.error.startswith("pdf_open_failed")


def test_empty_and_bad_gzip_bodies_return_errors():
    assert PymuPdf4LlmParser().parse(b"", url=_URL).error == "empty_input"
    assert PymuPdf4LlmParser().parse(b"\x1f\x8b not gzip", url=_URL).error.startswith("gzip_failed")


# ---------------------------------------------------------------------------
# The CLI (TASK-010): parse-pdfs reads response_body, writes parsed_documents
# ---------------------------------------------------------------------------


def _cache_entry(root: Path, name: str, url: str, body: bytes | None) -> Path:
    entry = root / name[:2] / name
    entry.mkdir(parents=True)
    (entry / "meta").write_text(repr({"url": url, "method": "GET"}), encoding="utf-8")
    if body is not None:
        (entry / "response_body").write_bytes(body)
    return entry


def test_cli_parses_response_body(tmp_path):
    import mongomock

    from config import MONGO_DB
    from corpus.parsers.pymupdf4llm import _cli

    url = "https://www.ema.europa.eu/en/documents/x.pdf"
    _cache_entry(tmp_path, "ab12", url, _FIXTURE.read_bytes())
    _cache_entry(tmp_path, "cd34", "https://www.ema.europa.eu/en/documents/no-body.pdf", None)
    client = mongomock.MongoClient()
    assert _cli(["--cache", str(tmp_path)], client=client) == 0
    rows = list(client[MONGO_DB]["parsed_documents"].find())
    assert len(rows) == 1  # the entry without a response_body is skipped
    (row,) = rows
    assert row["url"] == url and row["parser"] == "pymupdf4llm"
    assert row["parser_version"] == PARSER_VERSION and row["error"] == ""
    assert len(row["text"]) > 1000
    assert row["meta"]["cache_path"].endswith("ab12")
    assert not (tmp_path / "ab" / "ab12" / "parsed_pdf.pkl").exists()  # the cache is not written


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    import mongomock

    from config import MONGO_DB
    from corpus.parsers.pymupdf4llm import _cli

    _cache_entry(tmp_path, "ab12", "https://www.ema.europa.eu/en/documents/x.pdf", b"%PDF-1.5")
    client = mongomock.MongoClient()
    assert _cli(["--cache", str(tmp_path), "--dry-run"], client=client) == 0
    assert "Dry run: 1 would be parsed (of 1)" in capsys.readouterr().out
    assert client[MONGO_DB]["parsed_documents"].count_documents({}) == 0
