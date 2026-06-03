"""Unit tests for harness.indexing.links — main-content-scoped, component-aware
link extraction + typed link_context (ported from ema_scraper EmaPageParser)."""

from __future__ import annotations

import hashlib

from harness.indexing.links import extract_links

_BASE = "https://www.ema.europa.eu/en/human-regulatory/overview/nitrosamines"
_PDF = "https://www.ema.europa.eu/en/documents/scientific-guideline/qa-nitrosamines_en.pdf"

# A page with: site chrome OUTSIDE <main> + in breadcrumb/nav (must be dropped);
# inline links (incl. one external kept for the classification test, and a deeply
# nested + an accordion-body link); a .bcl-file card; a .bcl-listing card; a
# standalone anchor; skipped schemes; a self-ref; and an inline duplicate of the PDF.
_HTML = f"""
<html><body>
  <header><nav><a href="/en/about-us/contacts">Contacts (chrome)</a></nav></header>
  <nav class="breadcrumb"><a href="/en/about-us/cookies">Cookies (chrome)</a></nav>
  <main class="main-content-wrapper">
    <nav class="bcl-inpage-navigation"><a href="/en/about-us/careers">Careers (inpage)</a></nav>
    <p>An <a href="/en/human-regulatory/post-authorisation">inline page link</a> and an
       <a href="https://www.fda.gov/drugs">external</a> reference.</p>
    <div class="some-wrapper"><div class="deep"><p>Deeply
       <a href="/en/deep-nested">nested link</a></p></div></div>
    <div class="bcl-file" data-ema-document-type="scientific-guideline">
      <div class="file-title-metadata"><p class="file-title">Q&amp;A on nitrosamines</p></div>
      <div class="file-language-links">
        <p class="language-meta">English (EN) (310.46 KB - PDF)</p>
        <a href="{_PDF}">View</a>
      </div>
    </div>
    <div class="bcl-listing">
      <article class="listing-item card">
        <div class="card-body"><h4 class="card-title">
          <a href="/en/medicines/human/EPAR/example">Card title link</a></h4></div>
      </article>
    </div>
    <div class="accordion"><div class="accordion-item"><div class="accordion-body">
      <p>Accordion <a href="/en/accordion-target">body link</a></p>
    </div></div></div>
    <div><a href="/en/standalone">standalone in a div</a></div>
    <ul><li><a href="mailto:info@ema.europa.eu">email</a></li>
        <li><a href="tel:+3312345">phone</a></li>
        <li><a href="javascript:void(0)">js</a></li>
        <li><a href="#section">jump</a></li>
        <li><a href="/en/human-regulatory/overview/nitrosamines">self</a></li></ul>
    <p>Dup of the PDF as inline <a href="{_PDF}">same pdf</a></p>
  </main>
  <footer><a href="/en/about-us/legal">Legal (chrome)</a></footer>
</body></html>
"""

_POST = "https://www.ema.europa.eu/en/human-regulatory/post-authorisation"
_DEEP = "https://www.ema.europa.eu/en/deep-nested"
_CARD = "https://www.ema.europa.eu/en/medicines/human/EPAR/example"
_ACC = "https://www.ema.europa.eu/en/accordion-target"
_STANDALONE = "https://www.ema.europa.eu/en/standalone"
_EXT = "https://www.fda.gov/drugs"


def _links():
    return {link.tgt_url: link for link in extract_links(_HTML, _BASE)}


def test_main_scoping_keeps_exactly_main_content_links():
    assert set(_links()) == {_POST, _EXT, _DEEP, _PDF, _CARD, _ACC, _STANDALONE}


def test_chrome_outside_main_and_nav_excluded():
    urls = set(_links())
    assert not any(
        s in u for u in urls for s in ("/about-us/contacts", "cookies", "careers", "/about-us/legal")
    )


def test_file_component_context_document_type_and_title_anchor():
    link = _links()[_PDF]
    assert link.link_context == "file_component"
    assert link.document_type == "scientific-guideline"
    assert link.kind == "file"
    assert link.anchor == "Q&A on nitrosamines"  # file-title, not "View"/"same pdf"


def test_card_or_listing_context():
    assert _links()[_CARD].link_context == "card_or_listing"


def test_inline_context_incl_deeply_nested_and_accordion():
    links = _links()
    assert links[_POST].link_context == "inline"
    assert links[_DEEP].link_context == "inline"   # nested <div><div><p><a>
    assert links[_ACC].link_context == "inline"    # accordion-body recursion


def test_standalone_anchor_is_other():
    assert _links()[_STANDALONE].link_context == "other"


def test_dedup_richest_context_wins():
    pdfs = [link for link in extract_links(_HTML, _BASE) if link.tgt_url == _PDF]
    assert len(pdfs) == 1
    assert pdfs[0].link_context == "file_component"  # beats the inline dup


def test_classification_file_page_external():
    links = _links()
    assert links[_PDF].kind == "file"
    assert links[_POST].kind == "page"
    assert links[_EXT].kind == "external"


def test_skips_mailto_tel_js_fragment_and_self():
    urls = set(_links())
    assert not any("mailto" in u or "tel:" in u or "javascript" in u for u in urls)
    assert not any(u.endswith("#section") for u in urls)
    assert _BASE not in urls  # self-reference dropped


def test_relative_resolved_against_base():
    assert _DEEP in _links()  # leading-slash relative href resolved to absolute ema URL


def test_tgt_doc_id_is_sha256():
    link = next(iter(_links().values()))
    assert link.tgt_doc_id == hashlib.sha256(link.tgt_url.encode()).hexdigest()


def test_no_main_content_wrapper_returns_empty():
    assert extract_links("<html><body><p><a href='/x'>x</a></p></body></html>", _BASE) == []


def test_empty_html_returns_no_links():
    assert extract_links("", _BASE) == []
