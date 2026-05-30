"""Unit tests for harness.indexing.links — link_to extraction + classification."""

from __future__ import annotations

import hashlib

from harness.indexing.links import extract_links

_BASE = "https://www.ema.europa.eu/en/human-regulatory/overview/nitrosamines"

_HTML = """
<html><body>
  <a href="/en/documents/scientific-guideline/qa-nitrosamines_en.pdf">QA PDF</a>
  <a href="https://www.ema.europa.eu/en/human-regulatory/post-authorisation">Post-auth</a>
  <a href="https://www.fda.gov/drugs">FDA (external)</a>
  <a href="mailto:info@ema.europa.eu">Email</a>
  <a href="tel:+3312345">Phone</a>
  <a href="javascript:void(0)">JS</a>
  <a href="#section-2">Jump</a>
  <a href="/en/human-regulatory/overview/nitrosamines">Self</a>
  <a href="/en/documents/scientific-guideline/qa-nitrosamines_en.pdf">Dup PDF</a>
</body></html>
"""


def _by_url():
    return {link.tgt_url: link for link in extract_links(_HTML, _BASE)}


def test_skips_mailto_tel_js_fragment_and_self():
    urls = set(_by_url())
    assert not any("mailto" in u or "tel:" in u or "javascript" in u for u in urls)
    assert not any(u.endswith("#section-2") for u in urls)
    # self-reference to the base page is dropped
    assert _BASE not in urls


def test_dedup():
    pdf = "https://www.ema.europa.eu/en/documents/scientific-guideline/qa-nitrosamines_en.pdf"
    links = extract_links(_HTML, _BASE)
    assert sum(1 for link in links if link.tgt_url == pdf) == 1


def test_classification_file_page_external():
    links = _by_url()
    pdf = "https://www.ema.europa.eu/en/documents/scientific-guideline/qa-nitrosamines_en.pdf"
    page = "https://www.ema.europa.eu/en/human-regulatory/post-authorisation"
    ext = "https://www.fda.gov/drugs"
    assert links[pdf].kind == "file"
    assert links[page].kind == "page"
    assert links[ext].kind == "external"


def test_relative_resolved_against_base():
    links = _by_url()
    pdf = "https://www.ema.europa.eu/en/documents/scientific-guideline/qa-nitrosamines_en.pdf"
    assert pdf in links  # the leading-slash relative href resolved to an absolute ema URL


def test_tgt_doc_id_is_sha256():
    link = next(iter(_by_url().values()))
    assert link.tgt_doc_id == hashlib.sha256(link.tgt_url.encode()).hexdigest()


def test_empty_html_returns_no_links():
    assert extract_links("", _BASE) == []
