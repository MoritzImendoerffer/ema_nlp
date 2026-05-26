"""Unit tests for corpus/ingestion/pdf_normaliser.py (NARR-005)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from corpus.ingestion.pdf_normaliser import (
    EMA_REF_RE,
    DocumentInput,
    normalise_pdf_doc,
)

FIXTURES = Path(__file__).parent / "fixtures"
PDF_SAMPLE_MD = (FIXTURES / "ema_pdf_sample.md").read_text(encoding="utf-8")

PDF_URL = (
    "https://www.ema.europa.eu/en/documents/scientific-guideline/"
    "questions-and-answers-benzyl-alcohol-used-excipient_en.pdf"
)


def _mongo(markdown: str, url: str = PDF_URL, **extra) -> dict:
    return {"_id": url, "markdown": markdown, "error": "", **extra}


# ---------------------------------------------------------------------------
# Happy path with the fixture
# ---------------------------------------------------------------------------


def test_returns_document_input_from_fixture():
    out = normalise_pdf_doc(_mongo(PDF_SAMPLE_MD))
    assert isinstance(out, DocumentInput)
    assert out.source_url == PDF_URL
    assert out.source_type == "pdf"
    assert out.title == "Questions and answers on benzene impurities"
    assert out.markdown == PDF_SAMPLE_MD.strip()
    assert out.raw_byte_size == len(PDF_SAMPLE_MD.strip().encode("utf-8"))
    # Fixture has no reference number → committee/revision/date should be None
    assert out.reference_number is None
    assert out.committee is None
    assert out.revision is None
    assert out.last_updated is None


def test_topic_path_strips_filename():
    out = normalise_pdf_doc(_mongo(PDF_SAMPLE_MD))
    assert out is not None
    assert out.topic_path == "/en/documents/scientific-guideline/"


# ---------------------------------------------------------------------------
# Reference / committee / revision extractors
# ---------------------------------------------------------------------------


def test_reference_and_committee_extracted():
    md = (
        "EMA/CHMP/508188/2013 Rev. 2\n\n"
        "# Questions and answers on benzyl alcohol\n\n"
        "Body text here." * 5
    )
    out = normalise_pdf_doc(_mongo(md))
    assert out is not None
    assert out.reference_number == "EMA/CHMP/508188/2013"
    assert out.committee == "CHMP"
    assert out.revision == "2"


def test_unknown_committee_letters_normalise_to_none():
    md = "EMA/XYZ/1234/2024\n\n# Title\n\nBody"
    out = normalise_pdf_doc(_mongo(md))
    assert out is not None
    assert out.reference_number == "EMA/XYZ/1234/2024"
    assert out.committee is None  # XYZ is not in the whitelist


def test_revision_word_form_extracted():
    md = "EMA/PRAC/100/2021 Revision 4\n\n# Foo\n\nBody body body body"
    out = normalise_pdf_doc(_mongo(md))
    assert out is not None
    assert out.revision == "4"
    assert out.committee == "PRAC"


def test_last_updated_parsed_from_header_date():
    md = (
        "# Some title\n\n"
        "Adopted 21 March 2024 by the agency.\n\n"
        "Body body body body."
    )
    out = normalise_pdf_doc(_mongo(md))
    assert out is not None
    assert out.last_updated == datetime(2024, 3, 21, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Title fallbacks
# ---------------------------------------------------------------------------


def test_title_falls_back_to_url_basename_when_no_h1():
    md = "EMA/CHMP/1/2024\n\nNo header here, just prose. " * 5
    out = normalise_pdf_doc(_mongo(md))
    assert out is not None
    # URL basename: questions-and-answers-benzyl-alcohol-used-excipient_en
    assert out.title is not None
    assert "benzyl alcohol" in out.title.lower()


# ---------------------------------------------------------------------------
# Safe-default / None branches
# ---------------------------------------------------------------------------


def test_empty_markdown_returns_none():
    assert normalise_pdf_doc(_mongo("")) is None
    assert normalise_pdf_doc(_mongo("    \n\t  ")) is None


def test_error_field_returns_none():
    doc = _mongo(PDF_SAMPLE_MD)
    doc["error"] = "failed to parse"
    assert normalise_pdf_doc(doc) is None


def test_missing_url_returns_none():
    assert normalise_pdf_doc({"markdown": "hello world"}) is None


def test_empty_input_returns_none():
    assert normalise_pdf_doc({}) is None
    assert normalise_pdf_doc(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Regex sanity
# ---------------------------------------------------------------------------


def test_ema_ref_regex_matches_canonical_form():
    assert EMA_REF_RE.search("see EMA/CHMP/12345/2023 for details")
    assert EMA_REF_RE.search("EMA/PRAC/CHMP/99/2024 mixed")
    assert not EMA_REF_RE.search("EMA/12/2024")  # missing letters
