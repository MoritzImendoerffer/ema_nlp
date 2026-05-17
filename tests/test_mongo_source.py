"""Integration tests for corpus/sources/mongo_source.py.

Marked pytest.mark.integration — requires a live MongoDB at localhost:27017
with the ema_scraper database populated (run scripts/ingest_parsed_pdfs.py first).

Skip these in CI unless MONGO_INTEGRATION=1 is set.
"""

from __future__ import annotations

import os

import pytest

from corpus.models import QARecord
from corpus.sources.mongo_source import records_from_mongodb

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB = "ema_scraper"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def html_records() -> list[QARecord]:
    """Fetch a small sample of HTML-sourced QARecords."""
    recs: list[QARecord] = []
    for rec in records_from_mongodb(
        MONGO_URI,
        MONGO_DB,
        # Limit to a handful of Q&A-rich HTML pages to keep the test fast.
        html_query={"content_type": "text/html", "url": {"$regex": "questions-answers"}},
        pdf_query={"_id": {"$exists": False}},  # skip PDF branch
    ):
        recs.append(rec)
        if len(recs) >= 50:
            break
    return recs


@pytest.fixture(scope="module")
def pdf_records() -> list[QARecord]:
    """Fetch a small sample of PDF-sourced QARecords."""
    recs: list[QARecord] = []
    for rec in records_from_mongodb(
        MONGO_URI,
        MONGO_DB,
        html_query={"content_type": "__no_match__"},  # skip HTML branch
        pdf_query={"error": ""},
    ):
        recs.append(rec)
        if len(recs) >= 50:
            break
    return recs


def test_html_branch_yields_qa_records(html_records: list[QARecord]) -> None:
    assert len(html_records) >= 10, (
        f"Expected ≥10 QARecords from HTML branch, got {len(html_records)}"
    )


def test_pdf_branch_yields_qa_records(pdf_records: list[QARecord]) -> None:
    assert len(pdf_records) >= 10, (
        f"Expected ≥10 QARecords from PDF branch, got {len(pdf_records)}"
    )


def test_html_records_are_qa_record_instances(html_records: list[QARecord]) -> None:
    assert all(isinstance(r, QARecord) for r in html_records)


def test_pdf_records_are_qa_record_instances(pdf_records: list[QARecord]) -> None:
    assert all(isinstance(r, QARecord) for r in pdf_records)


def test_html_records_have_required_fields(html_records: list[QARecord]) -> None:
    for rec in html_records[:5]:
        assert rec.qa_id and len(rec.qa_id) == 16
        assert rec.question
        assert rec.answer
        assert rec.source_url.startswith("https://")
        assert rec.source_type == "html_accordion"


def test_pdf_records_have_required_fields(pdf_records: list[QARecord]) -> None:
    for rec in pdf_records[:5]:
        assert rec.qa_id and len(rec.qa_id) == 16
        assert rec.question
        assert rec.answer
        assert rec.source_url.startswith("https://")
        assert rec.source_type == "pdf"


def test_combined_yields_both_source_types() -> None:
    """Records from both HTML and PDF branches appear when both queries match."""
    # Scope HTML to exactly one page so the PDF branch is reached within the limit.
    # This URL is confirmed present in web_items and has ≥3 accordion Q&A pairs.
    _ONE_QA_PAGE = (
        "https://www.ema.europa.eu/en/compliance-marketing-authorisation-0/"
        "sampling-and-testing/sampling-testing-questions-answers"
    )
    seen_types: set[str] = set()
    count = 0
    for rec in records_from_mongodb(
        MONGO_URI,
        MONGO_DB,
        html_query={"content_type": "text/html", "url": _ONE_QA_PAGE},
        pdf_query={"error": ""},
    ):
        seen_types.add(rec.source_type)
        count += 1
        if count >= 100 or seen_types == {"html_accordion", "pdf"}:
            break
    assert "html_accordion" in seen_types, f"HTML branch produced no records (got: {seen_types})"
    assert "pdf" in seen_types, f"PDF branch produced no records (got: {seen_types})"
