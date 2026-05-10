"""Tests for corpus/extractors/html_extractor.py using real EMA fixture pages."""

import json
from pathlib import Path

import pytest

from corpus.extractors.html_extractor import extract_from_file, extract_from_html
from corpus.models import QARecord

FIXTURES = Path(__file__).parent / "fixtures"
META = json.loads((FIXTURES / "fixtures_meta.json").read_text())


@pytest.mark.parametrize("entry", META)
def test_extracts_records_from_real_pages(entry: dict) -> None:
    path = FIXTURES / entry["file"]
    records = extract_from_file(path, entry["url"])
    assert len(records) >= 3, f"Expected ≥3 Q&A pairs, got {len(records)} for {entry['url']}"


def test_all_records_are_qa_record_instances() -> None:
    entry = META[0]
    records = extract_from_file(FIXTURES / entry["file"], entry["url"])
    assert all(isinstance(r, QARecord) for r in records)


def test_fields_are_populated() -> None:
    entry = META[0]
    records = extract_from_file(FIXTURES / entry["file"], entry["url"])
    r = records[0]
    assert r.qa_id and len(r.qa_id) == 16
    assert r.question
    assert r.answer
    assert r.source_url == entry["url"]
    assert r.source_type == "html_accordion"
    assert r.topic_path.startswith("/")
    assert r.extraction_confidence in {"high", "medium", "low"}
    assert isinstance(r.cross_refs, list)


def test_qa_id_is_stable() -> None:
    """Same input always produces the same qa_id."""
    entry = META[0]
    r1 = extract_from_file(FIXTURES / entry["file"], entry["url"])
    r2 = extract_from_file(FIXTURES / entry["file"], entry["url"])
    assert [r.qa_id for r in r1] == [r.qa_id for r in r2]


def test_capture_rate_above_90_percent() -> None:
    """At least 90% of accordion-items should be captured as Q&A pairs."""
    from bs4 import BeautifulSoup

    total_items = 0
    total_captured = 0
    for entry in META:
        html = (FIXTURES / entry["file"]).read_text()
        soup = BeautifulSoup(html, "lxml")
        n_items = len(soup.find_all(class_="accordion-item"))
        n_captured = len(extract_from_html(html, entry["url"]))
        total_items += n_items
        total_captured += n_captured

    assert total_items > 0
    rate = total_captured / total_items
    assert rate >= 0.90, f"Capture rate {rate:.1%} below 90%"


def test_high_confidence_for_question_headings() -> None:
    """Items whose heading ends with '?' should get high confidence."""
    entry = META[0]
    records = extract_from_file(FIXTURES / entry["file"], entry["url"])
    question_items = [r for r in records if r.question.endswith("?")]
    if question_items:
        assert all(r.extraction_confidence == "high" for r in question_items)


def test_empty_html_returns_no_records() -> None:
    assert extract_from_html("<html><body></body></html>", "https://example.com") == []


def test_topic_path_derived_from_url() -> None:
    entry = META[0]
    records = extract_from_file(FIXTURES / entry["file"], entry["url"])
    assert records[0].topic_path != "/"
    # topic_path should reflect meaningful URL segments
    assert any(seg in records[0].topic_path for seg in ["post-authorisation", "human", "regulatory"])
