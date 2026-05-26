"""Unit tests for corpus/ingestion/html_normaliser.py (NARR-009)."""

from __future__ import annotations

from pathlib import Path

from corpus.ingestion.html_normaliser import normalise_html, normalise_html_doc
from corpus.ingestion.pdf_normaliser import DocumentInput

FIXTURES = Path(__file__).parent / "fixtures"
HTML_SAMPLE = (FIXTURES / "ema_html_sample.html").read_text(encoding="utf-8")
NAV_LANDING = (FIXTURES / "ema_nav_landing.html").read_text(encoding="utf-8")

HTML_URL = "https://www.ema.europa.eu/en/human-regulatory/post-authorisation/q-and-a-nitrosamines"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_content_page_yields_document_input():
    out = normalise_html(HTML_SAMPLE, HTML_URL)
    assert isinstance(out, DocumentInput)
    assert out.source_type == "html"
    assert out.source_url == HTML_URL
    assert out.markdown and len(out.markdown) >= 200
    # trafilatura keeps the headings + body — sanity-check on extracted text
    assert "NDMA" in out.markdown
    assert "Acceptable Intake" in out.markdown
    assert out.meta == {"extractor": "trafilatura"}


def test_reference_and_committee_extracted_from_html_body():
    out = normalise_html(HTML_SAMPLE, HTML_URL)
    assert out is not None
    assert out.reference_number == "EMA/CHMP/13279/2017"
    assert out.committee == "CHMP"
    assert out.revision == "2"


def test_topic_path_strips_to_directory():
    out = normalise_html(HTML_SAMPLE, HTML_URL)
    assert out is not None
    # URL has no filename extension → keep all segments
    assert out.topic_path == "/en/human-regulatory/post-authorisation/q-and-a-nitrosamines/"


def test_title_falls_back_to_url_segment_when_metadata_missing():
    # Minimal HTML with no title metadata but enough body to clear the landing guard.
    body = "<p>" + ("Acceptable Intake values are derived from carcinogenicity TD50. " * 20) + "</p>"
    html = f"<html><body><main>{body}</main></body></html>"
    out = normalise_html(html, HTML_URL)
    assert out is not None
    assert out.title is not None and out.title.strip()


# ---------------------------------------------------------------------------
# Landing-page guard
# ---------------------------------------------------------------------------


def test_landing_page_returns_none():
    """NARR-009 acceptance criterion: nav-only fixture returns None."""
    assert normalise_html(NAV_LANDING, HTML_URL) is None


def test_short_extraction_returns_none():
    html = "<html><body><p>Hello.</p></body></html>"
    assert normalise_html(html, HTML_URL) is None


def test_empty_html_or_url_returns_none():
    assert normalise_html("", HTML_URL) is None
    assert normalise_html(HTML_SAMPLE, "") is None


# ---------------------------------------------------------------------------
# normalise_html_doc (web_items adapter)
# ---------------------------------------------------------------------------


def test_normalise_html_doc_unwraps_one_element_lists():
    """web_items stores url/html_raw as 1-element lists."""
    doc = {"url": [HTML_URL], "html_raw": [HTML_SAMPLE]}
    out = normalise_html_doc(doc)
    assert isinstance(out, DocumentInput)
    assert out.source_url == HTML_URL


def test_normalise_html_doc_accepts_unwrapped_fields():
    doc = {"_id": HTML_URL, "html_raw": HTML_SAMPLE}
    out = normalise_html_doc(doc)
    assert isinstance(out, DocumentInput)


def test_normalise_html_doc_returns_none_for_missing_fields():
    assert normalise_html_doc({}) is None
    assert normalise_html_doc(None) is None  # type: ignore[arg-type]
    assert normalise_html_doc({"url": HTML_URL}) is None  # no html_raw
    assert normalise_html_doc({"url": [None], "html_raw": [None]}) is None
