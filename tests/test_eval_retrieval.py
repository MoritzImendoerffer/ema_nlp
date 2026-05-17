"""Unit tests for harness/eval_retrieval.py — uses synthetic gold sets, no MongoDB."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.eval_retrieval import plot_by_type, run_eval, score_item, summarise_by_type
from harness.retrieve import RetrievalResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(qa_id: str, source_url: str = "https://ema.europa.eu/qa") -> RetrievalResult:
    return (qa_id, 1.0, {"source_url": source_url, "topic_path": "/test", "cross_refs": []})


def _bench_item(
    bench_id: str,
    q_type: str,
    gold_qa_ids: list[str],
    gold_urls: list[str] | None = None,
    question: str = "What is X?",
) -> dict:
    gold_sources = [{"url": u, "page": None} for u in (gold_urls or ["https://ema.europa.eu/qa"])]
    return {
        "bench_id": bench_id,
        "question": question,
        "paraphrases": [],
        "type": q_type,
        "gold_answer": "Answer.",
        "gold_qa_ids": gold_qa_ids,
        "gold_sources": gold_sources,
        "topic_path": "/test",
        "notes": "",
    }


# ---------------------------------------------------------------------------
# score_item
# ---------------------------------------------------------------------------

def test_perfect_recall_and_precision():
    gold_ids = ["id-A", "id-B"]
    gold_urls = ["https://ema.europa.eu/doc1"]
    results = [
        _result("id-A", "https://ema.europa.eu/doc1"),
        _result("id-B", "https://ema.europa.eu/doc2"),
        _result("id-C", "https://ema.europa.eu/doc3"),
    ]
    scores = score_item(gold_ids, gold_urls, results, k=3)
    assert scores["recall_at_k"] == pytest.approx(1.0)
    assert scores["precision_at_k"] == pytest.approx(2 / 3)


def test_zero_recall():
    scores = score_item(["id-X"], ["https://ema.europa.eu/x"], [_result("id-Y")], k=1)
    assert scores["recall_at_k"] == 0.0
    assert scores["precision_at_k"] == 0.0
    assert scores["citation_accuracy"] == 0.0


def test_citation_accuracy_url_match():
    gold_urls = ["https://ema.europa.eu/doc1"]
    results = [
        _result("id-Z", "https://ema.europa.eu/doc1"),  # URL matches gold
    ]
    scores = score_item([], gold_urls, results, k=1)
    assert scores["citation_accuracy"] == pytest.approx(1.0)


def test_k_cutoff_applied():
    gold_ids = ["id-A"]
    gold_urls = ["https://ema.europa.eu/qa"]
    results = [
        _result("id-B"),
        _result("id-A"),  # rank 2 — outside k=1
    ]
    scores = score_item(gold_ids, gold_urls, results, k=1)
    assert scores["recall_at_k"] == 0.0  # id-A is rank 2, cut at k=1


def test_partial_recall():
    gold_ids = ["id-A", "id-B"]
    gold_urls = ["https://ema.europa.eu/qa"]
    results = [_result("id-A"), _result("id-C")]
    scores = score_item(gold_ids, gold_urls, results, k=2)
    assert scores["recall_at_k"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# summarise_by_type
# ---------------------------------------------------------------------------

def test_summarise_groups_by_type():
    per_item = [
        {"bench_id": "T1-001", "type": "T1", "recall_at_k": 1.0, "precision_at_k": 0.2, "citation_accuracy": 1.0},
        {"bench_id": "T1-002", "type": "T1", "recall_at_k": 0.5, "precision_at_k": 0.1, "citation_accuracy": 0.5},
        {"bench_id": "T2-001", "type": "T2", "recall_at_k": 0.0, "precision_at_k": 0.0, "citation_accuracy": 0.0},
    ]
    by_type = summarise_by_type(per_item)
    assert "T1" in by_type
    assert "T2" in by_type
    assert "overall" in by_type
    assert by_type["T1"]["recall_at_k"] == pytest.approx(0.75)
    assert by_type["T2"]["recall_at_k"] == pytest.approx(0.0)
    assert by_type["overall"]["recall_at_k"] == pytest.approx((1.0 + 0.5 + 0.0) / 3)


def test_summarise_n_items():
    per_item = [
        {"bench_id": "T1-001", "type": "T1", "recall_at_k": 1.0, "precision_at_k": 1.0, "citation_accuracy": 1.0},
        {"bench_id": "T3-001", "type": "T3", "recall_at_k": 0.5, "precision_at_k": 0.5, "citation_accuracy": 0.5},
    ]
    by_type = summarise_by_type(per_item)
    assert by_type["T1"]["n_items"] == 1
    assert by_type["overall"]["n_items"] == 2


# ---------------------------------------------------------------------------
# plot_by_type (smoke test — just checks no exceptions and file is created)
# ---------------------------------------------------------------------------

def test_plot_creates_png(tmp_path: Path):
    by_type = {
        "T1": {"recall_at_k": 0.8, "precision_at_k": 0.2, "citation_accuracy": 0.7, "n_items": 5},
        "T2": {"recall_at_k": 0.6, "precision_at_k": 0.15, "citation_accuracy": 0.5, "n_items": 3},
        "overall": {"recall_at_k": 0.7, "precision_at_k": 0.18, "citation_accuracy": 0.6, "n_items": 8},
    }
    out = tmp_path / "metrics.png"
    plot_by_type(by_type, k=10, out_path=out)
    assert out.exists()
    assert out.stat().st_size > 0


# ---------------------------------------------------------------------------
# run_eval (end-to-end with synthetic benchmark JSONL)
# ---------------------------------------------------------------------------

def test_run_eval_no_out_dir(tmp_path: Path):
    bench = tmp_path / "benchmark.jsonl"
    items = [
        _bench_item("T1-001", "T1", ["id-A"], ["https://ema.europa.eu/qa"]),
        _bench_item("T2-001", "T2", ["id-B"]),
    ]
    with bench.open("w") as fh:
        for item in items:
            fh.write((__import__("json").dumps(item)) + "\n")

    # retriever always returns id-A first
    def retrieve_fn(_query: str):
        return [_result("id-A")]

    output = run_eval(bench, retrieve_fn, k=1)
    assert output["k"] == 1
    assert len(output["per_item"]) == 2
    assert "T1" in output["by_type"]
    assert "overall" in output["by_type"]


def test_run_eval_writes_outputs(tmp_path: Path):
    bench = tmp_path / "benchmark.jsonl"
    item = _bench_item("T1-001", "T1", ["id-A"])
    bench.write_text(__import__("json").dumps(item) + "\n", encoding="utf-8")

    def retrieve_fn(_query: str):
        return [_result("id-A")]

    out_dir = tmp_path / "results"
    run_eval(bench, retrieve_fn, k=5, out_dir=out_dir)
    assert (out_dir / "results.json").exists()
    assert (out_dir / "metrics.png").exists()
