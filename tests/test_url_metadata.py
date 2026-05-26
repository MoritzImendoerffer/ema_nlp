"""Golden tests for corpus/metadata/url_metadata.py.

The ``topic_path`` field must match the legacy
``corpus/ingestion/pdf_normaliser._extract_topic_path`` and
``corpus/ingestion/html_normaliser._topic_path`` implementations byte-for-byte.
This file asserts that against representative EMA URLs plus edge cases.

``source_type`` is a URL-shape hint (the authoritative value is
``ParsedDocument.content_type``), so we exercise the unambiguous cases
(``.pdf``, no-extension HTML) plus a handful of edge cases.
"""

from __future__ import annotations

import pytest

from corpus.ingestion.html_normaliser import _topic_path as _html_topic_path
from corpus.ingestion.pdf_normaliser import _extract_topic_path as _pdf_topic_path
from corpus.metadata.url_metadata import UrlMetadata, url_metadata

# ---------------------------------------------------------------------------
# topic_path golden cases — parity with both legacy implementations
# ---------------------------------------------------------------------------

TOPIC_PATH_CASES = [
    # (url, expected_topic_path)
    # PDF with extension — filename dropped
    (
        "https://www.ema.europa.eu/en/documents/scientific-guideline/guideline.pdf",
        "/en/documents/scientific-guideline/",
    ),
    # PDF URL with query string (urlparse strips query from .path, so .pdf stays last)
    (
        "https://www.ema.europa.eu/en/documents/x.pdf?download=true",
        "/en/documents/",
    ),
    # HTML URL with trailing slash — no filename to drop
    (
        "https://www.ema.europa.eu/en/compliance-marketing-authorisation-0/sampling-testing-questions-answers/",
        "/en/compliance-marketing-authorisation-0/sampling-testing-questions-answers/",
    ),
    # HTML URL deep path, no extension, no trailing slash
    (
        "https://www.ema.europa.eu/en/medicines/human/EPAR/some-product",
        "/en/medicines/human/EPAR/some-product/",
    ),
    # Root URL
    ("https://www.ema.europa.eu/", "/"),
    # URL with no path at all
    ("https://www.ema.europa.eu", None),
    # Single-segment HTML path
    ("https://www.ema.europa.eu/en", "/en/"),
    # Filename in middle (only last is treated as filename)
    (
        "https://www.ema.europa.eu/en/foo.bar/q-and-a",
        "/en/foo.bar/q-and-a/",
    ),
    # Multiple trailing dots — last segment has '.' so it's treated as filename
    (
        "https://www.ema.europa.eu/en/foo/file.txt",
        "/en/foo/",
    ),
    # Path with only filename, no parent — drops to "/"
    ("https://www.ema.europa.eu/file.pdf", "/"),
]


@pytest.mark.parametrize("url,expected", TOPIC_PATH_CASES)
def test_topic_path_matches_expected(url: str, expected: str | None) -> None:
    assert url_metadata(url).topic_path == expected


@pytest.mark.parametrize("url,_expected", TOPIC_PATH_CASES)
def test_topic_path_matches_legacy_pdf_normaliser(url: str, _expected: str | None) -> None:
    """Golden: must match pdf_normaliser._extract_topic_path on every URL."""
    assert url_metadata(url).topic_path == _pdf_topic_path(url)


@pytest.mark.parametrize("url,_expected", TOPIC_PATH_CASES)
def test_topic_path_matches_legacy_html_normaliser(url: str, _expected: str | None) -> None:
    """Golden: must match html_normaliser._topic_path on every URL."""
    assert url_metadata(url).topic_path == _html_topic_path(url)


# ---------------------------------------------------------------------------
# source_type cases
# ---------------------------------------------------------------------------


def test_source_type_pdf_extension() -> None:
    md = url_metadata("https://www.ema.europa.eu/en/documents/x.pdf")
    assert md.source_type == "pdf"


def test_source_type_pdf_uppercase() -> None:
    md = url_metadata("https://www.ema.europa.eu/en/documents/X.PDF")
    assert md.source_type == "pdf"


def test_source_type_pdf_with_query_string() -> None:
    # urlparse drops the query string from .path, so the path still ends .pdf
    md = url_metadata("https://www.ema.europa.eu/en/documents/x.pdf?download=1")
    assert md.source_type == "pdf"


def test_source_type_html_no_extension() -> None:
    md = url_metadata("https://www.ema.europa.eu/en/sampling-questions-answers")
    assert md.source_type == "html"


def test_source_type_html_trailing_slash() -> None:
    md = url_metadata("https://www.ema.europa.eu/en/sampling-questions-answers/")
    assert md.source_type == "html"


def test_source_type_html_explicit_extension() -> None:
    md = url_metadata("https://www.ema.europa.eu/en/page.html")
    assert md.source_type == "html"


def test_source_type_unknown_for_other_extensions() -> None:
    md = url_metadata("https://www.ema.europa.eu/en/data.xml")
    assert md.source_type == "unknown"


def test_source_type_unknown_for_empty_path() -> None:
    md = url_metadata("https://www.ema.europa.eu")
    assert md.source_type == "unknown"


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------


def test_returns_url_metadata_instance() -> None:
    assert isinstance(url_metadata("https://x.test/"), UrlMetadata)


def test_url_metadata_is_frozen() -> None:
    md = url_metadata("https://x.test/")
    with pytest.raises(Exception):
        md.topic_path = "/other/"  # type: ignore[misc]
