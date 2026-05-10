"""Tests for corpus/extractors/pdf_extractor.py."""

from pathlib import Path

import pytest

from corpus.extractors.pdf_extractor import (
    _extract_reference_number,
    _extract_revision,
    _split_into_qa,
    extract_from_markdown,
    extract_from_pdf,
)
from corpus.models import QARecord

FIXTURES = Path(__file__).parent / "fixtures"
PDF_FIXTURE = FIXTURES / "fixture_pdf_0.pdf"
PDF_URL = (
    "https://www.ema.europa.eu/en/documents/scientific-guideline/"
    "questions-and-answers-benzyl-alcohol-used-excipient-medicinal-products-human-use_en.pdf"
)

# ---------------------------------------------------------------------------
# Unit tests on helper functions (no PDF needed)
# ---------------------------------------------------------------------------

SAMPLE_MARKDOWN = """\
EMA/CHMP/508188/2013

# Questions and answers on benzyl alcohol

## **1. What is benzyl alcohol and why is it used as an excipient?**

Benzyl alcohol is an aromatic alcohol. See Q&A 2 for medicinal products containing it.

## **2. Which medicinal products contain benzyl alcohol?**

Benzyl alcohol is mainly used in parenteral preparations.

## **3. What are the safety concerns?**

The main problem is accumulation in neonates. See Q 1 for background.

## References

1. Some reference.
"""


def test_split_into_qa_count() -> None:
    pairs = _split_into_qa(SAMPLE_MARKDOWN)
    assert len(pairs) == 3


def test_split_into_qa_stops_at_references() -> None:
    pairs = _split_into_qa(SAMPLE_MARKDOWN)
    questions = [q for _, q, _ in pairs]
    assert not any("reference" in q.lower() for q in questions)


def test_split_extracts_question_text() -> None:
    pairs = _split_into_qa(SAMPLE_MARKDOWN)
    _, q, _ = pairs[0]
    assert "benzyl alcohol" in q.lower()
    assert "?" in q


def test_split_extracts_answer_text() -> None:
    pairs = _split_into_qa(SAMPLE_MARKDOWN)
    _, _, a = pairs[0]
    assert "aromatic alcohol" in a.lower()


def test_extract_reference_number() -> None:
    ref = _extract_reference_number(SAMPLE_MARKDOWN)
    assert ref == "EMA/CHMP/508188/2013"


def test_extract_revision_not_present() -> None:
    assert _extract_revision(SAMPLE_MARKDOWN) == ""


def test_extract_revision_present() -> None:
    text = "EMA/409815/2020 Rev.23\nSome content"
    assert _extract_revision(text) == "Rev.23"


def test_cross_refs_resolved() -> None:
    records = extract_from_markdown(SAMPLE_MARKDOWN, "https://example.com/qa.pdf")
    # Q1 answer references Q2 ("See Q&A 2")
    q1 = records[0]
    assert len(q1.cross_refs) == 1
    assert q1.cross_refs[0] == records[1].qa_id


def test_cross_refs_bidirectional() -> None:
    records = extract_from_markdown(SAMPLE_MARKDOWN, "https://example.com/qa.pdf")
    # Q3 references Q1 ("See Q 1")
    q3 = records[2]
    assert records[0].qa_id in q3.cross_refs


def test_extract_from_markdown_returns_qa_records() -> None:
    records = extract_from_markdown(SAMPLE_MARKDOWN, "https://example.com/qa.pdf")
    assert all(isinstance(r, QARecord) for r in records)


def test_extract_from_markdown_empty_returns_empty() -> None:
    assert extract_from_markdown("No headings here.", "https://example.com") == []


# ---------------------------------------------------------------------------
# Integration test on real PDF fixture
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not PDF_FIXTURE.exists(), reason="PDF fixture not present")
def test_extract_from_real_pdf() -> None:
    records = extract_from_pdf(PDF_FIXTURE, PDF_URL)
    assert len(records) >= 3, f"Expected ≥3 Q&A pairs, got {len(records)}"


@pytest.mark.skipif(not PDF_FIXTURE.exists(), reason="PDF fixture not present")
def test_real_pdf_reference_number() -> None:
    records = extract_from_pdf(PDF_FIXTURE, PDF_URL)
    assert records[0].reference_number == "EMA/CHMP/508188/2013"


@pytest.mark.skipif(not PDF_FIXTURE.exists(), reason="PDF fixture not present")
def test_real_pdf_record_structure() -> None:
    records = extract_from_pdf(PDF_FIXTURE, PDF_URL)
    r = records[0]
    assert r.qa_id and len(r.qa_id) == 16
    assert r.source_type == "pdf"
    assert r.topic_path.startswith("/")
    assert r.extraction_confidence in {"high", "medium", "low"}
