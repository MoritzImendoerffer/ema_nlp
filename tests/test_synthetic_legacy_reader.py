"""Tests for corpus/sources/synthetic_legacy_reader.py.

Uses mongomock so these don't require a live MongoDB. Verifies the bridge
from legacy ``parsed_pdfs`` + ``web_items`` rows into ParsedDocument
instances suitable for :func:`harness.embed_pg.sync`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

try:
    import mongomock
    import mongomock.collection as _mc

    _HAS_MONGOMOCK = True
except ImportError:  # pragma: no cover
    _HAS_MONGOMOCK = False
    mongomock = None  # type: ignore[assignment]
    _mc = None  # type: ignore[assignment]

from corpus.parsers.base import ParsedDocument
from corpus.parsers.trafilatura import LANDING_PAGE_ERROR
from corpus.sources import synthetic_legacy_reader as slr

FIXTURES = Path(__file__).parent / "fixtures"
HTML_SAMPLE = (FIXTURES / "ema_html_sample.html").read_text(encoding="utf-8")
HTML_LANDING = (FIXTURES / "ema_nav_landing.html").read_text(encoding="utf-8")

PDF_URL = "https://www.ema.europa.eu/en/documents/a.pdf"
HTML_URL = "https://www.ema.europa.eu/en/qa-page"

pytestmark = pytest.mark.skipif(
    not _HAS_MONGOMOCK and not os.getenv("MONGO_URI"),
    reason="mongomock not installed and MONGO_URI not set",
)


@pytest.fixture(autouse=True)
def _patch_mongomock_bulk_sort(monkeypatch):
    if not _HAS_MONGOMOCK:
        return
    _orig = _mc.BulkOperationBuilder.add_update

    def _patched(self, *args, sort=None, **kwargs):
        return _orig(self, *args, **kwargs)

    monkeypatch.setattr(_mc.BulkOperationBuilder, "add_update", _patched)


@pytest.fixture
def client():
    if not _HAS_MONGOMOCK:
        pytest.skip("mongomock not installed")
    c = mongomock.MongoClient()
    yield c
    c.close()


def _seed(client) -> None:
    pdfs = client[slr.MONGO_DB]["parsed_pdfs"]
    pdfs.insert_many(
        [
            {
                "_id": f"{PDF_URL}#a",
                "markdown": "# PDF A\n\nbody body body",
                "error": "",
                "cache_path": "/tmp/a",
                "ingested_at": "2026-05-01",
            },
            {
                "_id": f"{PDF_URL}#b",
                "markdown": "# PDF B\n\nmore body",
                "error": "",
            },
            {
                "_id": f"{PDF_URL}#err",
                "markdown": "",
                "error": "pymupdf4llm crashed",
            },
        ]
    )
    web = client[slr.MONGO_DB]["web_items"]
    web.insert_many(
        [
            {
                "_id": HTML_URL,
                "url": [HTML_URL],
                "content_type": "text/html",
                "html_raw": [HTML_SAMPLE],
            },
            {
                "_id": HTML_URL + "/landing",
                "url": [HTML_URL + "/landing"],
                "content_type": "text/html",
                "html_raw": [HTML_LANDING],
            },
            # Not-HTML row should be skipped (filtered by content_type query)
            {
                "_id": HTML_URL + "/blob",
                "url": [HTML_URL + "/blob"],
                "content_type": "application/zip",
                "html_raw": ["<zip>"],
            },
        ]
    )


# ---------------------------------------------------------------------------
# PDF path
# ---------------------------------------------------------------------------


def test_pdf_rows_emit_parsed_document(client):
    _seed(client)
    docs = list(
        slr.iter_parsed_documents_from_legacy(client=client, content_types=["application/pdf"])
    )
    assert len(docs) == 2  # the empty-text + error row is skipped (no markdown)
    for d in docs:
        assert isinstance(d, ParsedDocument)
        assert d.parser == "pymupdf4llm"
        assert d.parser_version == slr.LEGACY_VERSION
        assert d.content_type == "application/pdf"
        assert d.text_format == "markdown"


def test_pdf_rows_carry_legacy_meta(client):
    _seed(client)
    docs = list(
        slr.iter_parsed_documents_from_legacy(client=client, content_types=["application/pdf"])
    )
    # Look for the row that had cache_path + ingested_at
    a_doc = next(d for d in docs if d.url == f"{PDF_URL}#a")
    assert a_doc.meta.get("cache_path") == "/tmp/a"
    assert a_doc.meta.get("ingested_at") == "2026-05-01"


def test_pdf_error_rows_filtered_out_by_default(client):
    _seed(client)
    docs = list(
        slr.iter_parsed_documents_from_legacy(client=client, content_types=["application/pdf"])
    )
    assert not any(d.url.endswith("#err") for d in docs)


# ---------------------------------------------------------------------------
# HTML path
# ---------------------------------------------------------------------------


def test_html_rows_emit_parsed_document(client):
    _seed(client)
    docs = list(
        slr.iter_parsed_documents_from_legacy(client=client, content_types=["text/html"])
    )
    # landing page is filtered out; non-html row never matches the query
    assert len(docs) == 1
    d = docs[0]
    assert d.parser == "trafilatura"
    assert d.parser_version == slr.LEGACY_VERSION
    assert d.content_type == "text/html"
    assert d.text_format == "markdown"
    assert d.url == HTML_URL
    assert d.error == ""
    assert d.text  # non-empty


def test_html_landing_page_filtered_out_by_default(client):
    _seed(client)
    docs = list(
        slr.iter_parsed_documents_from_legacy(client=client, content_types=["text/html"])
    )
    assert not any(d.error == LANDING_PAGE_ERROR for d in docs)


def test_include_errors_returns_landing_pages(client):
    _seed(client)
    docs = list(
        slr.iter_parsed_documents_from_legacy(
            client=client, content_types=["text/html"], include_errors=True
        )
    )
    # Landing page now included
    assert any(d.error == LANDING_PAGE_ERROR for d in docs)


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------


def test_combined_streams_both_collections(client):
    _seed(client)
    docs = list(slr.iter_parsed_documents_from_legacy(client=client))
    parsers = {d.parser for d in docs}
    assert "pymupdf4llm" in parsers
    assert "trafilatura" in parsers


def test_url_list_unwrapping(client):
    """web_items stores url as [url]; the reader must unwrap to a string."""
    _seed(client)
    docs = list(
        slr.iter_parsed_documents_from_legacy(client=client, content_types=["text/html"])
    )
    assert all(isinstance(d.url, str) for d in docs)
