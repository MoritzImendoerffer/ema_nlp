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


# --- row selection by parser preference (TASK-002 of work unit 27) -----------
#
# Until 2026-11-25 ``iter_source_rows`` kept the first clean row per URL in cursor
# order. Rows of one URL come in insertion order, which nothing guarantees, so a
# re-parse never replaced the row the graph was built from.

_U = "https://www.ema.europa.eu/en/documents/scientific-guideline/guideline-x_en.pdf"
_H = "https://www.ema.europa.eu/en/human-regulatory-overview/page-x"


def _row(url, parser, version, parsed_at, *, ct="application/pdf", text="text"):
    return {
        "url": url, "parser": parser, "parser_version": version, "parsed_at": parsed_at,
        "content_type": ct, "text_format": "markdown", "error": "", "text": text,
    }


def _selected(client, **kw):
    from harness.indexing.ingest import iter_source_rows

    return list(iter_source_rows(ScopeConfig(), client=client, **kw))


@pytest.mark.parametrize("legacy_first", [True, False])
def test_preferred_parser_row_wins(legacy_first):
    """The legacy PDF row beats a newer byte parse of the same parser name (decisions A, D)."""
    legacy = _row(_U, "pymupdf4llm", "legacy", dt.datetime(2026, 5, 27, 22, 0))
    new = _row(_U, "pymupdf4llm", "1.27.2.3", dt.datetime(2026, 11, 25, 9, 0))
    c = mongomock.MongoClient()
    c[MONGO_DB][PARSED_COLLECTION].insert_many([legacy, new] if legacy_first else [new, legacy])
    rows = _selected(c)
    assert [(r["parser"], r["parser_version"]) for r in rows] == [("pymupdf4llm", "legacy")]


def test_newest_row_of_one_parser_wins():
    c = mongomock.MongoClient()
    c[MONGO_DB][PARSED_COLLECTION].insert_many([
        _row(_H, "trafilatura", "legacy", dt.datetime(2026, 5, 27, 22, 0), ct="text/html"),
        _row(_H, "trafilatura", "2.0.0", dt.datetime(2026, 11, 25, 9, 0), ct="text/html"),
    ])
    assert [r["parser_version"] for r in _selected(c)] == ["2.0.0"]


def test_unlisted_parser_falls_back_to_newest(caplog):
    """Decision F: no listed parser → the newest clean row, a warning and a count."""
    from harness.indexing.ingest import SelectionStats, iter_source_groups

    c = mongomock.MongoClient()
    c[MONGO_DB][PARSED_COLLECTION].insert_many([
        _row(_U, "llamahub_pdf_PDFReader", "0.6.0", dt.datetime(2026, 5, 27, 22, 0)),
        _row(_U, "llamahub_pdf_PDFReader", "0.7.0", dt.datetime(2026, 6, 1, 8, 0)),
    ])
    stats = SelectionStats()
    with caplog.at_level("WARNING"):
        choices = list(iter_source_groups(ScopeConfig(), client=c, stats=stats))
    assert [ch.selected["parser_version"] for ch in choices] == ["0.7.0"]
    assert choices[0].fallback is True
    assert stats.fallbacks == 1 and stats.urls == 1
    assert any("no parser preference entry matches" in r.message for r in caplog.records)


def test_old_rule_row_is_the_first_row_of_the_cursor():
    """``old_rule`` is the row the build kept before 2026-11-25: the first one the cursor gave."""
    from harness.indexing.ingest import iter_source_groups

    first = _row(_U, "pymupdf4llm", "1.27.2.3", dt.datetime(2026, 11, 25, 9, 0))
    legacy = _row(_U, "pymupdf4llm", "legacy", dt.datetime(2026, 5, 27, 22, 0))
    c = mongomock.MongoClient()
    c[MONGO_DB][PARSED_COLLECTION].insert_many([first, legacy])
    (choice,) = list(iter_source_groups(ScopeConfig(), client=c))
    assert choice.old_rule["parser_version"] == "1.27.2.3"
    assert choice.selected["parser_version"] == "legacy"
    assert choice.fallback is False


def test_error_rows_are_never_selected():
    c = mongomock.MongoClient()
    bad = _row(_H, "trafilatura", "2.0.0", dt.datetime(2026, 11, 25, 9, 0), ct="text/html")
    bad["error"] = "landing_page_below_min_chars"
    c[MONGO_DB][PARSED_COLLECTION].insert_many([
        _row(_H, "trafilatura", "legacy", dt.datetime(2026, 5, 27, 22, 0), ct="text/html"), bad,
    ])
    assert [r["parser_version"] for r in _selected(c)] == ["legacy"]


def test_selection_uses_a_given_preference():
    from harness.indexing.parser_preference import PreferenceEntry

    c = mongomock.MongoClient()
    c[MONGO_DB][PARSED_COLLECTION].insert_many([
        _row(_U, "pymupdf4llm", "legacy", dt.datetime(2026, 5, 27, 22, 0)),
        _row(_U, "pymupdf4llm", "1.27.2.3", dt.datetime(2026, 11, 25, 9, 0)),
    ])
    pref = {"application/pdf": [PreferenceEntry("pymupdf4llm", None)]}
    assert [r["parser_version"] for r in _selected(c, preference=pref)] == ["1.27.2.3"]
