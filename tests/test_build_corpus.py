"""Tests for corpus/build_corpus.py — pure dedup/filter/write logic."""

from __future__ import annotations

import json
from pathlib import Path

from corpus.build_corpus import CorpusStats, _dedup_key, _is_landing_page, build_corpus
from corpus.models import QARecord


def _make_record(
    question: str = "What is the acceptable intake?",
    answer: str = "The acceptable intake is 1.5 μg/day.",
    source_url: str = "https://www.ema.europa.eu/en/qa",
    source_type: str = "html_accordion",
    topic_path: str = "/human-regulatory/safety",
    cross_refs: list | None = None,
    confidence: str = "high",
) -> QARecord:
    from corpus.extractors.html_extractor import _qa_id
    return QARecord(
        qa_id=_qa_id(source_url, question),
        question=question,
        answer=answer,
        source_url=source_url,
        source_type=source_type,  # type: ignore[arg-type]
        source_title="Test page",
        topic_path=topic_path,
        cross_refs=cross_refs or [],
        extraction_confidence=confidence,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Dedup key
# ---------------------------------------------------------------------------

def test_dedup_key_normalises_whitespace_and_case() -> None:
    r1 = _make_record(question="What is the AI?")
    r2 = _make_record(question="  what  is  the  AI?  ")
    assert _dedup_key(r1) == _dedup_key(r2)


def test_dedup_key_differs_for_different_questions() -> None:
    r1 = _make_record(question="What is the AI?")
    r2 = _make_record(question="What is the LoQ?")
    assert _dedup_key(r1) != _dedup_key(r2)


# ---------------------------------------------------------------------------
# Landing-page filter
# ---------------------------------------------------------------------------

def test_landing_page_detected() -> None:
    rec = _make_record(answer="See below.", cross_refs=[], confidence="low")
    assert _is_landing_page(rec)


def test_real_qa_not_filtered() -> None:
    rec = _make_record(confidence="high")
    assert not _is_landing_page(rec)


def test_landing_page_with_crossrefs_not_filtered() -> None:
    # Even low-confidence records with cross_refs are kept.
    rec = _make_record(answer="Short.", cross_refs=["Q1"], confidence="low")
    assert not _is_landing_page(rec)


def test_landing_page_with_long_answer_not_filtered() -> None:
    rec = _make_record(answer="x" * 200, confidence="low")
    assert not _is_landing_page(rec)


# ---------------------------------------------------------------------------
# build_corpus — dedup behaviour
# ---------------------------------------------------------------------------

def test_dedup_drops_html_when_pdf_exists(tmp_path: Path) -> None:
    q = "What is the acceptable intake?"
    html_rec = _make_record(question=q, source_type="html_accordion", source_url="https://ema.europa.eu/html")
    pdf_rec = _make_record(question=q, source_type="pdf", source_url="https://ema.europa.eu/pdf")

    stats = build_corpus([html_rec, pdf_rec], tmp_path / "corpus.jsonl")

    lines = (tmp_path / "corpus.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["source_type"] == "pdf"
    assert stats.deduped == 1
    assert stats.total_output == 1


def test_dedup_keeps_html_when_no_pdf(tmp_path: Path) -> None:
    rec = _make_record(source_type="html_accordion")
    stats = build_corpus([rec], tmp_path / "corpus.jsonl")
    assert stats.deduped == 0
    assert stats.total_output == 1


def test_dedup_keeps_distinct_questions(tmp_path: Path) -> None:
    r1 = _make_record(question="What is the AI?")
    r2 = _make_record(question="What is the LoQ?")
    stats = build_corpus([r1, r2], tmp_path / "corpus.jsonl")
    assert stats.total_output == 2
    assert stats.deduped == 0


# ---------------------------------------------------------------------------
# build_corpus — landing-page filter
# ---------------------------------------------------------------------------

def test_landing_pages_filtered(tmp_path: Path) -> None:
    real = _make_record(question="What is the AI?", confidence="high")
    landing = _make_record(question="Overview", answer="See below.", confidence="low")

    stats = build_corpus([real, landing], tmp_path / "corpus.jsonl")

    assert stats.filtered == 1
    assert stats.total_output == 1


# ---------------------------------------------------------------------------
# build_corpus — stats and output
# ---------------------------------------------------------------------------

def test_stats_counts_correct(tmp_path: Path) -> None:
    records = [
        _make_record(question=f"Question {i}?", source_url=f"https://ema.europa.eu/{i}")
        for i in range(5)
    ]
    stats = build_corpus(records, tmp_path / "corpus.jsonl")

    assert isinstance(stats, CorpusStats)
    assert stats.total_input == 5
    assert stats.total_output == 5
    assert stats.deduped == 0
    assert stats.filtered == 0


def test_output_is_valid_jsonl(tmp_path: Path) -> None:
    records = [_make_record(question=f"Q{i}?", source_url=f"https://ema.europa.eu/{i}") for i in range(3)]
    build_corpus(records, tmp_path / "corpus.jsonl")

    lines = (tmp_path / "corpus.jsonl").read_text().splitlines()
    assert len(lines) == 3
    for line in lines:
        obj = json.loads(line)
        assert "qa_id" in obj
        assert "question" in obj
        assert "answer" in obj


def test_by_source_type_breakdown(tmp_path: Path) -> None:
    records = [
        _make_record(question="Q1?", source_type="html_accordion", source_url="https://ema.europa.eu/1"),
        _make_record(question="Q2?", source_type="html_accordion", source_url="https://ema.europa.eu/2"),
        _make_record(question="Q3?", source_type="pdf", source_url="https://ema.europa.eu/3"),
    ]
    stats = build_corpus(records, tmp_path / "corpus.jsonl")
    assert stats.by_source_type["html_accordion"] == 2
    assert stats.by_source_type["pdf"] == 1


def test_logs_written(tmp_path: Path) -> None:
    q = "What is the AI?"
    html_rec = _make_record(question=q, source_type="html_accordion", source_url="https://ema.europa.eu/h")
    pdf_rec = _make_record(question=q, source_type="pdf", source_url="https://ema.europa.eu/p")
    landing = _make_record(question="Nav page", answer="x", confidence="low")

    build_corpus([html_rec, pdf_rec, landing], tmp_path / "corpus.jsonl")

    dedup_log = tmp_path / "corpus_dedup_log.jsonl"
    filter_log = tmp_path / "corpus_filter_log.jsonl"
    assert dedup_log.exists()
    assert filter_log.exists()
    assert len(dedup_log.read_text().splitlines()) == 1
    assert len(filter_log.read_text().splitlines()) == 1


def test_output_path_created_if_missing(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "corpus.jsonl"
    build_corpus([_make_record()], nested)
    assert nested.exists()


def test_no_pymongo_import() -> None:
    """build_corpus.py must not contain a pymongo import."""
    import re
    src = (Path(__file__).parent.parent / "corpus" / "build_corpus.py").read_text()
    imports = [ln for ln in src.splitlines() if re.match(r"^\s*(import|from)\s+.*pymongo", ln)]
    assert not imports, f"build_corpus.py must not import pymongo; found: {imports}"
