"""Unit tests for harness.indexing.ingest — Mongo parsed_documents -> IR (mongomock)."""

from __future__ import annotations

import datetime as dt
import hashlib

import mongomock
import pytest

from config import MONGO_DB
from harness.indexing.document_metadata import upsert_badges, upsert_doc_types
from harness.indexing.ingest import PARSED_COLLECTION, ingest
from harness.indexing.profiles import (
    ChunkingConfig,
    IndexConfig,
    IndexProfile,
    RetrievalConfig,
    ScopeConfig,
)

_PDF_URL = "https://www.ema.europa.eu/en/documents/scientific-guideline/qa-nitrosamines_en.pdf"
_HTML_URL = "https://www.ema.europa.eu/en/human-regulatory/overview/nitrosamines"
_HTML_RAW = f"""
<html><body>
  <header><nav><a href="/en/about-us/cookies">chrome (ignored)</a></nav></header>
  <main class="main-content-wrapper">
    <span class="ema-bg-category"><span class="label">Human</span></span>
    <p>See <a href="{_PDF_URL}">the QA PDF</a> and an
       <a href="https://www.fda.gov/x">external</a> reference.</p>
  </main>
</body></html>
"""


def _md(title: str, ref: str | None = None) -> str:
    head = f"# {title}\n\n"
    if ref:
        head += f"{ref}\n\n26 October 2023\n\n"
    return head + ("This is a sentence about regulatory guidance and limits. " * 60)


def _seed(client):
    col = client[MONGO_DB][PARSED_COLLECTION]
    now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    col.insert_many(
        [
            {  # PDF — valid, has committee via reference
                "url": _PDF_URL, "parser": "pymupdf4llm", "parser_version": "1.27.2",
                "parsed_at": now, "content_type": "application/pdf", "text_format": "markdown",
                "error": "", "text": _md("Questions and answers on nitrosamines", "EMA/CHMP/409815/2020 Rev. 23"),
            },
            {  # duplicate URL, different parser — dedup should keep one
                "url": _PDF_URL, "parser": "llamahub_pdf_PDFReader", "parser_version": "0.4",
                "parsed_at": now, "content_type": "application/pdf", "text_format": "markdown",
                "error": "", "text": _md("Questions and answers on nitrosamines", "EMA/CHMP/409815/2020 Rev. 23"),
            },
            {  # HTML — valid, no committee
                "url": _HTML_URL, "parser": "trafilatura", "parser_version": "1.12",
                "parsed_at": now, "content_type": "text/html", "text_format": "markdown",
                "error": "", "text": _md("Nitrosamines overview"),
            },
            {  # error row — skipped
                "url": "https://www.ema.europa.eu/en/x.pdf", "parser": "pymupdf4llm",
                "parser_version": "1.27.2", "parsed_at": now, "content_type": "application/pdf",
                "text_format": "markdown", "error": "parse failed", "text": "",
            },
            {  # non-pdf/html content type — skipped
                "url": "https://www.ema.europa.eu/en/data.json", "parser": "x", "parser_version": "1",
                "parsed_at": now, "content_type": "application/json", "text_format": "plain",
                "error": "", "text": _md("data"),
            },
        ]
    )


def _profile(**scope_kw) -> IndexProfile:
    return IndexProfile(
        name="t",
        index=IndexConfig(
            chunking=ChunkingConfig(chunk_sizes=[512, 128]),
            scope=ScopeConfig(**scope_kw),
        ),
        retrieval=RetrievalConfig(),
    )


@pytest.fixture
def client():
    c = mongomock.MongoClient()
    _seed(c)
    return c


def _html_lookup(url):
    return _HTML_RAW if url == _HTML_URL else None


def test_ingest_dedups_and_skips_error_and_nontext(client):
    docs = ingest(_profile(), mongo_client=client, html_lookup=_html_lookup)
    urls = sorted(d.source_url for d in docs)
    assert urls == [_PDF_URL, _HTML_URL] or urls == sorted([_PDF_URL, _HTML_URL])
    assert len(docs) == 2  # error row + json row skipped, pdf dedup'd


def test_doc_id_source_type_and_metadata(client):
    by_url = {d.source_url: d for d in ingest(_profile(), mongo_client=client, html_lookup=_html_lookup)}
    pdf = by_url[_PDF_URL]
    assert pdf.doc_id == hashlib.sha256(_PDF_URL.encode()).hexdigest()
    assert pdf.source_type == "pdf"
    assert pdf.metadata["committee"] == "CHMP"
    assert pdf.metadata["topic_path"] == "/en/documents/scientific-guideline/"
    assert pdf.title == "Questions and answers on nitrosamines"
    assert pdf.chunk_nodes  # non-empty hierarchy


def test_html_doc_has_links_pdf_does_not(client):
    by_url = {d.source_url: d for d in ingest(_profile(), mongo_client=client, html_lookup=_html_lookup)}
    assert by_url[_PDF_URL].links == []
    html_links = {link.tgt_url for link in by_url[_HTML_URL].links}
    assert _PDF_URL in html_links          # HTML page links to the PDF (links_to edge)


def test_limit_caps_results(client):
    assert len(ingest(_profile(limit=1), mongo_client=client, html_lookup=_html_lookup)) == 1


def test_committee_scope_filter(client):
    docs = ingest(_profile(committee=["CHMP"]), mongo_client=client, html_lookup=_html_lookup)
    assert [d.source_url for d in docs] == [_PDF_URL]   # only the CHMP doc survives


# --- document_metadata join (doc_type / audience / site_topic) ---------------


def test_metadata_row_joined_onto_doc(client):
    upsert_doc_types({_PDF_URL: "scientific-guideline"}, client=client)
    upsert_badges(
        [{"url": _HTML_URL, "audience": "Veterinary", "site_topic": "Pharmacovigilance"}],
        client=client,
    )
    by_url = {d.source_url: d for d in ingest(_profile(), mongo_client=client, html_lookup=_html_lookup)}
    assert by_url[_PDF_URL].metadata["doc_type"] == "scientific-guideline"
    # the stored row wins over the live badge in the fixture HTML ("Human")
    assert by_url[_HTML_URL].metadata["audience"] == "Veterinary"
    assert by_url[_HTML_URL].metadata["site_topic"] == "Pharmacovigilance"


def test_without_enrichment_badges_fall_back_to_live_extraction(client):
    by_url = {d.source_url: d for d in ingest(_profile(), mongo_client=client, html_lookup=_html_lookup)}
    assert by_url[_HTML_URL].metadata["audience"] == "Human"   # from _HTML_RAW badge
    assert by_url[_HTML_URL].metadata["site_topic"] is None
    assert by_url[_PDF_URL].metadata.get("doc_type") is None   # no live source for doc_type
